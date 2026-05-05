# 抖音收藏夹 AI 笔记批量导出

批量遍历抖音网页版某个**个人收藏夹**中的视频：

- 有 `AI笔记 / AI字幕 / 文字稿` 就导出文本
- 没有就跳过
- 每个视频单独导出一个 `.txt`
- 同时生成 `index.json` 清单

## 运行要求

- Python 3.12+
- 已安装 `playwright`
- 首次如果没有浏览器内核，执行：

```powershell
python -m playwright install chromium
```

## 快速开始

### 方式 1：按收藏夹名称抓

```powershell
python .\douyin_ai_notes_export.py --collection-name "你的收藏夹名称"
```

### 方式 2：给收藏夹页面或收藏夹内任意视频页面 URL

```powershell
python .\douyin_ai_notes_export.py --collection-url "https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection"
```

如果你给的是某个视频 URL，例如：

```text
https://www.douyin.com/user/self?from_tab_name=main&modal_id=7615277045148405019&showTab=favorite_collection
```

脚本会自动去掉 `modal_id`，回到该收藏夹的视频列表页继续跑。

## 推荐试跑

先只跑前 3 个，确认页面结构和账号状态没问题：

```powershell
python .\douyin_ai_notes_export.py --collection-name "你的收藏夹名称" --limit 3
```

## 脚本行为

1. 启动持久化浏览器（默认目录：`.browser-profile`）
2. 打开抖音收藏夹入口
3. 如遇登录/验证码，等待你在浏览器里手动完成
4. 进入目标收藏夹
5. 自动滚动，收集当前收藏夹内所有视频 URL
6. 逐个打开视频
7. 尝试点击 `AI笔记 / AI字幕 / 文字稿 / 字幕`
8. 提取文本并写入本地；若没有有效文本则跳过

## 输出目录

默认输出到：

```text
exports/<收藏夹名>/
```

其中包含：

- `0001_<modal_id>.txt`
- `0002_<modal_id>.txt`
- `index.json`

`index.json` 里会记录：

- 收藏夹名
- 收藏夹 URL
- 总视频数
- 成功导出数
- 跳过数
- 每个视频的状态、输出文件、失败原因

## 常用参数

```powershell
python .\douyin_ai_notes_export.py `
  --collection-name "你的收藏夹名称" `
  --output-dir .\exports `
  --profile-dir .\.browser-profile `
  --limit 10 `
  --timeout-ms 2200
```

说明：

- `--collection-name`：按可见名称点击收藏夹；失败时会回退为手动选择
- `--collection-url`：直接打开目标收藏夹页
- `--limit`：只处理前 N 个视频，适合试跑
- `--timeout-ms`：点击 AI 笔记后等待页面稳定的时长
- `--headless`：无头模式；**不建议**，因为登录和验证码更难处理

## 注意

- 抖音页面结构经常变化，脚本已经做了多路兜底（DOM + 网络响应文本提取），但后续仍可能需要微调选择器。
- 最稳妥的使用方式是：
  - 先登录
  - 手动打开目标收藏夹
  - 再回终端按回车让脚本继续
- 如果某些视频确实没有 `AI笔记 / AI字幕` 入口，脚本会直接跳过并在 `index.json` 里写原因。
