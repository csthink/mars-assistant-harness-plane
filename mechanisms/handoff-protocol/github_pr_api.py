#!/usr/bin/env python3
"""github-pr-api: publish --request <仓外 JSON> [--root <任务 worktree>] [--json]。

要求显式 GitHub 配置；复用共用交接、发布、申报、回读和 result/v1。
不合并或清理；连接配置不授予发布权限。
"""
import sys
sys.dont_write_bytecode = True
import handoff_workflow as flow


def main(argv=None):
    return flow.main(argv, required_provider='github', description=__doc__)


if __name__ == '__main__':
    sys.exit(main())
