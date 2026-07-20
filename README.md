# YLDQ 6.0 远程监控系统

面向 YLDQ 6.0 下位机的实时监控、可视化、控制和配置软件。通信协议固定为 Modbus V7（协议字 `0x0700`），串口直接传输标准 Modbus RTU ADU，不使用 SLIP，也不兼容旧版寄存器地址。

## 功能

- 三路温湿度、主显示温湿度、压力、流量与呼吸状态
- HTC1、HTC2、防冻加热、告警输出状态和累计动作次数
- 上阀、左阀、右阀的位置、执行状态、故障、电流和控制来源
- 多通道实时曲线、告警事件、Modbus 请求与异常诊断
- 运行区安全控制（HR800–807）
- 配置暂存、回读、提交和放弃事务
- 最新时间单位：流量无变化报警、阀门重启保护和强制关闭按“天”；阀门冷却延时与防冻关闭延时按“小时”
- 多设备串口配置、采集会话记录和数据导出

预测推荐、参数模拟、旧版离线客户报告和旧 Modbus 线圈模型均已删除。

## 启动测试

双击：

```text
启动源码调试.bat
```

或在 PowerShell 中运行：

```powershell
cd "E:\project\5.0.0\xishiqi5.0.0\docs\新程序运行数据分析系统"
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app\dashboard_server.py
```

浏览器访问：`http://127.0.0.1:8765`

进入“设备管理”配置串口和从站地址，选择设备后点击“启动监控”。首次收到数据时会校验 FC04 地址 0 必须等于 `0x0700`。

## 自动测试

```powershell
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check app\web\app.js
```

## 打包

运行 `scripts\打包分析系统EXE.bat`。输出位于 `release\YLDQ6.0远程监控系统`。

## 结构

- `app/dashboard_server.py`：监控 HTTP API 和静态资源服务
- `app/live_acquisition_service.py`：多设备采集、控制、配置与记录
- `app/live_register_catalog.py`：Modbus V7 唯一点表
- `app/modbus_v7_codec.py`：寄存器类型编解码
- `app/modbus_v7_config.py`：配置事务
- `app/monitoring_projection.py`：界面监控模型
- `app/web/`：最终监控界面
- `tests/`：协议、采集、投影和记录测试
- `docs/design/`：架构设计
