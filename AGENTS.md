# YLDQ 6.0 上位机开发约束

## 目标

本项目是 YLDQ 6.0 下位机的远程监控、控制、配置和数据记录上位机，不再承担旧版离线数据分析、参数预测、推荐或模拟工作。

## 协议约束

- 唯一协议为 Modbus V7，协议字 `0x0700`。
- 串口使用标准裸 Modbus RTU ADU，不使用 SLIP。
- 支持 FC02、FC03、FC04、FC06、FC16；禁止 FC01、FC05、FC15。
- 不兼容旧版寄存器地址，不添加旧点 ID、地址别名或迁移分支。
- 寄存器地址只能定义在 `app/live_register_catalog.py`。
- F32、U32、U64 均为高字在前。
- 配置区写入必须暂存、回读，再通过 HR3 写 `0xC6A6` 提交或 `0xD15C` 放弃。
- 即时控制只能写 HR800–807。

## 核心模块

- `app/dashboard_server.py`：HTTP API 和 Web 静态服务。
- `app/live_acquisition_service.py`：串口采集、控制、配置事务和记录。
- `app/live_modbus_client.py`：标准 Modbus RTU 主站客户端。
- `app/live_register_catalog.py`：V7 唯一点表。
- `app/live_polling_commands.py`：固定合法轮询块。
- `app/modbus_v7_codec.py`：类型编解码。
- `app/modbus_v7_config.py`：配置事务。
- `app/monitoring_projection.py`：监控视图模型。
- `app/web/`：无框架 HTML/CSS/JavaScript 前端。

## 验证

```powershell
python -m compileall -q app scripts
python -m unittest discover -s tests -v
node --check app/web/app.js
```

修改界面后必须实际启动 `app/dashboard_server.py`，检查 `/api/health`、`/api/bootstrap` 和浏览器控制台。

## 代码规范

- 对话、说明、文档和注释使用中文。
- Python 使用类型标注，公共数据返回 JSON 可序列化对象。
- 设备写操作必须校验点表权限和地址区域，不开放任意自动 Raw Hex 写入。
- 多设备共享串口时保持顺序访问，不并发抢占同一串口。
- 不恢复预测推荐、参数模拟、客户静态报告或旧 CSV 分析代码。
