"""Bounded, bidirectional stdio JSON-RPC transport."""
import asyncio
from collections import deque
import contextlib
import sys

from runtime.protocol import Fault, METHODS, decode, encode, invalid

class Stdio:
    def __init__(self):
        self.dispatcher = None
        self.pending, self.requests = {}, {}
        self.control, self.events = deque(), deque()
        self.buffered = 0
        self.condition = asyncio.Condition()
        self.next_id = 0
        self.closing = False

    async def send(self, value, event=False, on_written=None):
        raw = encode(value, self.dispatcher.limits)
        if len(raw) > self.dispatcher.limits["bufferBytes"]:
            raise Fault("RESOURCE_LIMIT", "Frame exceeds negotiated buffer")
        sent = asyncio.get_running_loop().create_future()
        async with self.condition:
            await self.condition.wait_for(lambda: self.closing or self.buffered + len(raw) <= self.dispatcher.limits["bufferBytes"])
            if self.closing:
                raise ConnectionError("Connection closed")
            (self.events if event else self.control).append((raw, sent, value.get("params", {}).get("event", {}).get("subscriptionId") if event else None, on_written))
            self.buffered += len(raw)
            self.condition.notify_all()
        await sent
        return len(raw)

    async def write_loop(self, writer):
        controls = 0
        while not self.closing:
            async with self.condition:
                await self.condition.wait_for(lambda: self.closing or self.control or self.events)
                if self.closing:
                    return
                queue = self.control if self.control and (controls < 3 or not self.events) else self.events
                raw, sent, subscription_id, on_written = queue.popleft()
                controls = controls + 1 if queue is self.control else 0
            try:
                current = any(sub["id"] == subscription_id and sub["enabled"] for sub in self.dispatcher.subscriptions.values())
                if subscription_id is None or current:
                    writer.write(raw)
                    await writer.drain()
                    if on_written:
                        on_written()
                if not sent.done():
                    sent.set_result(None)
            finally:
                async with self.condition:
                    self.buffered -= len(raw)
                    self.condition.notify_all()

    async def call_host(self, method, params, timeout):
        if len(self.pending) >= self.dispatcher.limits["inFlight"]:
            raise Fault("RESOURCE_LIMIT", "Host requests at capacity", recovery="retry-later")
        self.next_id += 1
        request_id = "r:" + str(self.next_id)
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            async with asyncio.timeout(timeout):
                await self.send(dict(jsonrpc="2.0", id=request_id, method=method, params=params))
                return await future
        except TimeoutError as exc:
            raise Fault("RESULT_UNKNOWN", "Host RPC timed out", recovery="query") from exc
        finally:
            self.pending.pop(request_id, None)

    async def handle(self, frame):
        request_id, p = frame["id"], frame["params"]
        try:
            result = await self.dispatcher.dispatch(frame["method"], p)
            await self.send(dict(jsonrpc="2.0", id=request_id, result=result))
            if frame["method"] == "runtime.events.subscribe":
                sub = self.dispatcher.subscriptions.get(p["scopeRef"])
                if sub and sub["id"] == result["subscriptionId"]:
                    sub["enabled"] = True
            if self.dispatcher.shutdown:
                self.closing = True
                self.reader_transport.close()
        except Fault as exc:
            try:
                await self.send(dict(jsonrpc="2.0", id=request_id, error=exc.error(p)))
            except (Fault, ConnectionError):
                self.closing = True
                self.reader_transport.close()
        except (ConnectionError, asyncio.CancelledError):
            raise
        except Exception:
            # Never expose request, file paths, credentials, or traceback on stdout.
            await self.send(dict(jsonrpc="2.0", id=request_id,
                                 error=Fault("RESULT_UNKNOWN", "Internal domain failure", rpc=-32603).error(p)))
        finally:
            self.requests.pop(request_id, None)

    async def receive(self, raw):
        frame = decode(raw, self.dispatcher.limits)
        if frame.get("jsonrpc") != "2.0":
            raise invalid("Invalid JSON-RPC version", rpc=-32600)
        request_id = frame.get("id")
        if "method" not in frame:
            if not isinstance(request_id, str) or not request_id.startswith("r:") or request_id not in self.pending:
                raise invalid("Uncorrelated Host response", rpc=-32600)
            if set(frame) not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"}):
                raise invalid("Invalid Host response shape", rpc=-32600)
            future = self.pending[request_id]
            if future.done():
                raise invalid("Duplicate Host response", rpc=-32600)
            if "error" in frame:
                self.dispatcher.schemas.validate("RpcError", frame["error"])
                error = frame["error"]
                future.set_exception(Fault(error["data"]["code"], error["message"], rpc=error["code"],
                                           recovery=error["data"]["recovery"], absence=error["data"]["absenceProven"]))
            else:
                future.set_result(frame["result"])
            return
        if set(frame) != {"jsonrpc", "id", "method", "params"} or not isinstance(request_id, str) or not request_id.startswith("h:") or not isinstance(frame["method"], str):
            raise invalid("Invalid request shape or direction", rpc=-32600)
        if not isinstance(frame["params"], dict):
            await self.send(dict(jsonrpc="2.0", id=request_id, error=invalid("Params must be an object").error()))
            return
        if request_id in self.requests:
            raise invalid("Duplicate in-flight request id", rpc=-32600)
        control = frame["method"] in ("runtime.health", "runtime.operation.get", "runtime.operation.cancel", "runtime.events.ack")
        limit = self.dispatcher.limits["inFlight"]
        regular_limit = max(1, limit - min(2, limit-1))
        if len(self.requests) >= (limit if control else regular_limit):
            await self.send(dict(jsonrpc="2.0", id=request_id,
                error=Fault("RESOURCE_LIMIT", "In-flight request limit", recovery="retry-later").error(frame["params"])))
            return
        task = asyncio.create_task(self.handle(frame))
        self.requests[request_id] = task

    async def event_loop(self):
        d = self.dispatcher
        while not self.closing:
            await asyncio.sleep(.02)
            if not d.ready:
                continue
            for scope, sub in list(d.subscriptions.items()):
                if not sub["enabled"]:
                    continue
                try:
                    # Revocation is checked at every production batch, not only authorize.
                    await d.authorize(dict(context=d.context, scopeRef=scope), "runtime.events.subscribe")
                    state = d.domain.read()
                    source = d.scope(state, scope)
                    if source["epoch"] != sub["epoch"] or source["streamId"] != sub["stream"] or int(source["logFloor"]) > sub["sent"]:
                        raise Fault("RESYNC_REQUIRED")
                    for item in source["events"]:
                        if int(item["seq"]) <= sub["sent"]:
                            continue
                        if d.subscriptions.get(scope) is not sub:
                            break
                        if int(item["seq"]) != sub["sent"] + 1:
                            raise Fault("RESYNC_REQUIRED")
                        event = dict(subscriptionId=sub["id"], **item)
                        d.schemas.validate("Event", event)
                        frame = dict(jsonrpc="2.0", method="runtime.event", params=dict(context=d.context, event=event))
                        size = len(encode(frame, d.limits))
                        if len(sub["outstanding"]) >= d.limits["eventWindow"] or sum(b for _, b in sub["outstanding"]) + size > d.limits["bufferBytes"]:
                            break
                        sequence = int(item["seq"])
                        def delivered(sub=sub, sequence=sequence, size=size):
                            sub["sent"] = sequence
                            sub["outstanding"].append((sequence, size))
                        await self.send(frame, event=True, on_written=delivered)
                    if sub["sent"] == int(source["seq"]) and sub["caught"] != sub["sent"]:
                        event = dict(kind="stream.caughtUp", subscriptionId=sub["id"], scopeRef=scope,
                                     streamId=sub["stream"], epoch=sub["epoch"], throughSeq=str(sub["sent"]))
                        await self.send(dict(jsonrpc="2.0", method="runtime.event", params=dict(context=d.context, event=event)), event=True)
                        sub["caught"] = sub["sent"]
                except Fault:
                    # No claim of continuity after revocation or a log gap. Host must resync.
                    sub["enabled"] = False

    async def run(self):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=1048576)
        self.reader_transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
        write_transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
        writer = asyncio.StreamWriter(write_transport, protocol, None, loop)
        writer_task = asyncio.create_task(self.write_loop(writer))
        event_task = asyncio.create_task(self.event_loop())
        try:
            buffer = bytearray()
            while not self.closing:
                chunk = await reader.read(min(8192, self.dispatcher.limits["frameBytes"]))
                if not chunk:
                    if buffer:
                        await self.send(dict(jsonrpc="2.0", id=None, error=invalid("Incomplete frame", rpc=-32700).error()))
                    break
                buffer.extend(chunk)
                while b"\n" in buffer:
                    end = buffer.index(b"\n") + 1
                    if end > self.dispatcher.limits["frameBytes"]:
                        self.closing = True
                        break
                    raw = bytes(buffer[:end])
                    del buffer[:end]
                    try:
                        await self.receive(raw)
                    except Fault as exc:
                        await self.send(dict(jsonrpc="2.0", id=None, error=exc.error()))
                    # Let initialize apply its negotiated bound before the next frame.
                    await asyncio.sleep(0)
                if len(buffer) >= self.dispatcher.limits["frameBytes"]:
                    break
        finally:
            self.closing = True
            self.reader_transport.close()
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Host disconnected"))
            tasks = list(self.requests.values()) + [writer_task, event_task]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            write_transport.close()
