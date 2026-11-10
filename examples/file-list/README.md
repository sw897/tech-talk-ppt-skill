# 文件清单整理示例

合成教学内容，介绍输入、澄清、证据回查和接续交付，不代表真实业务执行。image.json为6页整页生图；hybrid.json前6页讲相同内容，后4页为原生表格与记录示例，用于局部修改验证。混合页先设计完整生成构图和文字槽，再以原生标题、标签、连线与表格完成解释；参数修改同时更新对应讲稿。

源稿见[source.md](source.md)。采用快照包含源稿哈希，原生备注与审阅由实际PPT生成。图片由内置生图工具生成，原生尺寸、哈希、示例提示词与参考职责见[generation-manifest.json](generation-manifest.json)。

在Skill目录安装依赖后，从任意目录运行：

```text
node <skill>/scripts/build_pptx.mjs --spec <skill>/examples/file-list/image.json --output <new-output>/image.pptx
node <skill>/scripts/build_pptx.mjs --spec <skill>/examples/file-list/hybrid.json --output <new-output>/hybrid.pptx
```

输出目录和文件由使用者选择。不要覆盖已有成果。实际渲染、审阅与修订命令见[装配方法](../../references/pptx-assembly.md)及[修订方法](../../references/revision-and-review.md)。示例默认使用微软雅黑，可通过theme.font替换为目标系统已安装的字体。
