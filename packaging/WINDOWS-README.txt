PowerBid Lab - Windows x64
===========================

使用方法
--------
1. 双击 PowerBidLab.exe。
2. 程序会在本机启动一个仅监听 127.0.0.1 的 Streamlit 服务，并自动打开默认浏览器。
3. 关闭浏览器标签页不会立即结束本地服务；需要结束程序时可在任务管理器中结束 PowerBidLab.exe。

说明
----
- 当前版本是课程研讨 / 教学原型，不是生产级电力交易系统。
- 示例数据是 synthetic 仿真数据，不代表真实市场。
- 第一次启动单文件 EXE 需要先解压内置 Python 运行环境，可能等待数秒。
- Windows SmartScreen 可能提示“未知发布者”，原因是当前构建没有商业代码签名证书；文件由 GitHub Actions 从仓库源码自动构建。

排错
----
如果启动失败，程序会把错误日志写入：
%LOCALAPPDATA%\PowerBidLab\startup-error.log

把该日志发给开发者即可继续定位。
