"""版本信息 — 更新机制以此文件作为版本唯一来源。

发布新版本时递增 __version__ 并提交推送；客户端通过
raw.githubusercontent.com 读取本文件对比版本。
"""

__version__ = "0.7.1"
