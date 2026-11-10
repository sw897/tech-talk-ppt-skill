# PPT装配与依赖

Node.js＋PptxGenJS负责装配，Python负责检查、受控修改、渲染调度和审阅。生图由当前Agent调用内置工具，脚本只消费已实际取得的图片。

## 最短命令

在Skill目录执行 `npm ci --ignore-scripts --no-audit --no-fund`。需要审阅联系表时安装requirements.txt。随后可从任意工作目录运行：

```text
node <skill>/scripts/build_pptx.mjs --spec <project>/deck.json --output <project>/deck.pptx
python <skill>/scripts/inspect_pptx.py <project>/deck.pptx --report <project>/structure.json
python <skill>/scripts/render_pptx.py <project>/deck.pptx --output-dir <project>/render --backend auto
python <skill>/scripts/review.py <project>/deck.pptx --images <project>/render --output <project>/review.html
```

Python 3.10+；Node.js 18+。构建锁定PptxGenJS 4.0.1和JSZip 3.10.1，完整依赖由package-lock.json记录。Pillow仅用于审阅图像尺寸与联系表，不用于替代生成图。

## 采用快照

deck.json是本次装配所用内容、备注与素材的快照。既有分镜可以继续作为正文维护源，采用时核对实际文本与哈希；审阅页从实际PPT读取文字与备注，不另手写副本。

顶层字段：`schema_version: 1`、`mode: image|hybrid`、`title`、可选`canvas`、`theme`、`footer`与`slides`。页面使用唯一稳定的`id`、`title`、`notes`。image模式每页指定`image`，可附sha256和素材性质；hybrid模式使用`elements`。

元素使用稳定`id`与`type`：text、image、shape、line、table。坐标均为画布px，`box:[x,y,width,height]`；字体尺寸也是px，装配时按96dpi换成英寸和pt。图片路径相对快照文件；每张图可写入`sha256`核对选用字节。`kind`用generated或original表明性质，不能据字段本身声称已运行。

text包含`text`、`fontSize`、可选color／bold／align。image包含`path`和`fit:contain|cover`，默认contain。shape只用于承载确有含义的结构；table包含二维`rows`与`columnWidths`。line使用`from`、`to`及可选`arrow`。可参考随包示例。

每页标题与页脚在hybrid模式为原生对象。image模式只放完整页面图，不重复叠标题。原生备注在两种模式都写入PPT。文本框与表格按实际内容分配空间，不能靠自动缩字掩盖溢出。

混合页元素按列表顺序绘制，原生标题与页脚最后叠排。完整构图背景可作为第一个image元素；其文字槽和连接通道需在生图时规划。页面的`titleStyle`可指定`box`、`fontSize`及`rule:false`，供封面或已设计的构图采用；`showFooter:false`隐藏封面页脚，`footerRule:false`只隐藏分隔线。表格可用`headerFill`、`bodyFill`、`columnStyles`及按“行,列”索引的`cellStyles`设置字号、字重与颜色，让数值、量纲和待确认项保持清晰主次；行列内容仍为原生表格。

## 实际渲染

Windows的auto优先选择可用的WPS／PowerPoint COM导出；通过只读、无窗口的文档调用导出PNG，并关闭本次打开的文档。已有其他演示文稿时不退出共享程序。可用`--backend wps|powerpoint`明确选择。

其他系统可用`--backend libreoffice`，需要soffice和pdftoppm，或显式提供两者路径。转换使用本次临时profile和输出目录，不修改已有LibreOffice配置。字体需在目标机器安装；主题可指定当地可用的字体，不随包分发商业字体。

创建PPTX、XML检查、原生导出和真实放映是不同层次。没有渲染器时不能用另画的HTML代替PPT导出。当前静态工具不验证动画、声音、投影或讲述计时。

## 导出Skill

```text
python <skill>/scripts/export_skill.py --output-dir <destination>
```

导出.zip与.skill两个同内容包，排除node_modules、虚拟环境、缓存、凭据文件和示例输出PPT；核对相对资源、CRC、逐文件哈希和包内路径。安装包保留依赖声明与必要示例输入。导出不安装、不上传、不创建远程。

可将导出目录设为仓库内的dist；dist、outputs、artifacts与.local均不纳入安装包。
