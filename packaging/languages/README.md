# Inno Setup 简体中文语言文件（随仓库分发）

本目录的 `ChineseSimplified.isl` 用于生成中文安装包界面。**不要**删改其头部来源信息。

## 来源与版本

- 文件：`ChineseSimplified.isl`
- 上游仓库：<https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation>
- 上游 commit：`c8a3e44d3a`（2025-10-17，“针对 6.5 优化翻译一致性”）
- 适配 Inno Setup：6.5.x（本项目 CI 安装并固定使用 Inno Setup 6.5.4）
- 许可证：MIT（Copyright (c) 2019-2020 kirakira）
  - 上游 LICENSE：<https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation/blob/master/LICENSE>
  - 该翻译文件自身是 MIT 许可；Inno Setup 软件本体使用 Inno Setup License
    （见 <https://jrsoftware.org/files/is/license.txt>），构建工具不随安装包再分发。

## 为什么随仓库携带

Inno Setup 官方发行版直到 7.1 才内置 `ChineseSimplified.isl`；GitHub Actions 的
`windows-latest` 镜像默认不再预装 Inno Setup（2025-09 起），本项目 CI 通过
Chocolatey 固定安装 Inno Setup 6.5.4。把语言文件放进仓库可以保证：

1. 安装包界面稳定为简体中文，不依赖构建机是否带中文语言文件；
2. 构建可复现，不联网下载翻译文件。

## 升级注意

升级 Inno Setup 大版本时，请同时更新本文件到对应上游版本，并重跑
`ISCC.exe packaging\engineerdiff.iss` 与 CI 构建。若某个消息键在新版本中不存在，
Inno Setup 只会给出警告并回退英文默认文案，不会导致编译失败（已核对 6.5.4 源码
`Compiler.SetupCompiler.pas` 的 `EnumMessagesProc` 逻辑）。
