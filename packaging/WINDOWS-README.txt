PowerBid Lab - Windows x64
===========================

推荐安装方式
------------
1. 双击 PowerBidLab-Setup-x64.exe。
2. 按安装向导完成安装。
3. 从开始菜单启动 “PowerBid Lab”；如安装时勾选，也可从桌面快捷方式启动。
4. 程序会直接打开独立的 PowerBid Lab 桌面窗口，不会再跳转到默认浏览器。

便携版
------
如果不想安装，可解压 PowerBidLab-Portable-x64.zip，然后运行其中的 PowerBidLab.exe。
不要只单独复制 PowerBidLab.exe；便携版需要同目录中的运行库文件。

实现说明
--------
- Windows 桌面外壳使用 pywebview / Microsoft Edge WebView2。
- 报价界面在应用内部渲染；本地服务仅监听 127.0.0.1，不对局域网或公网开放。
- 当前版本是课程研讨 / 教学原型，不是生产级电力交易系统。
- 示例数据是 synthetic 仿真数据，不代表真实市场。
- Windows 11 通常自带 WebView2 Runtime；绝大多数已更新的 Windows 10 机器也已通过 Microsoft Edge 获得它。

排错
----
如果启动失败，程序会把错误日志写入：
%LOCALAPPDATA%\PowerBidLab\startup-error.log

本地服务日志位于：
%LOCALAPPDATA%\PowerBidLab\server.log

把上述日志发给开发者即可继续定位。
