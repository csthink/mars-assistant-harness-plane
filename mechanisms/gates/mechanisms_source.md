# 机制单元花名册（MECHANISMS）

> 本文件是**单元花名册与分发清单**：列出 `mechanisms/` 下的全部机制单元，以及本仓对安装载荷的贡献。
>
> 只指路。单元目录文法、花名册完备性核对要求与载荷边界的规则，一律见 `mechanisms/repo-layout/HarnessPlane_Repo_Layout_Design_v1.md`，本文件不复述、不承载状态。

## 单元表

下表由磁盘发现的单元目录派生（`manifest --write` 生成；核对 = 人工可选 `manifest`）。

<!--table:units-->

## 分发清单

本仓对安装载荷的贡献 = 机制区三个整树，按目录取整：`mechanisms/` · `.agents/` · `apps/`。

实例区与证据区严禁入包。载荷的组装方式与载体形态由 gov-t13 分发设计裁定。
