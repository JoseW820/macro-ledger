# Macro Observer Mobile

这是 Macro Ledger 的 Android 手机端发布文件。APK 使用本项目的月度数据记录页面作为 WebView 入口，保留六个主题的数据总览、42 项指标走势、月份归档、每月个人记录空间，以及 Excel/CSV 预览、重复检查和确认导入流程。

## 文件

- `macro-observer.apk`：可直接安装的 Android APK。
- `macro-data-mobile-unified.html`：APK 内嵌的网页源文件，便于查看和修改界面。
- `macro-data-mobile-data.js`：示例月度指标记录。

## 使用说明

1. 安装 `macro-observer.apk`。
2. 在“上传数据”中选择一个月份的数据文件夹或多个 Excel/CSV 文件。
3. 检查解析预览、重复项和异常项。
4. 点击“确认导入”后写入本机记录。
5. 在“个人记录”中选择月份，保存文字观察并添加本地附件。

Excel 解析组件从 SheetJS 的 HTTPS 地址加载，因此首次解析 Excel 需要网络连接。数据记录保存在设备本地，不会自动上传到服务器。

## 构建与安全

APK 使用 Android v2/v3 签名。仓库不包含签名 keystore、个人数据或构建缓存；重新构建时应使用自己的签名密钥。
