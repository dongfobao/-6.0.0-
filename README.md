# YLDQ 6.0 远程监控系统

面向 YLDQ 6.0 下位机的实时监控、可视化、控制和配置软件。通信协议固定为 Modbus V10.0（协议字 `0x0A00`），串口直接传输标准 Modbus RTU ADU，不使用 SLIP，也不兼容旧版寄存器地址。

## 功能

- 三路温湿度、主显示温湿度、压力、流量与呼吸状态
- HTC1、HTC2、防冻加热、告警输出状态和累计动作次数
- 上阀、左阀、右阀的位置、执行状态、故障、电流和控制来源
- 多通道实时曲线、告警事件、Modbus 请求与异常诊断
- 运行控制使用 COIL0–29，阀门动作保护状态使用 DI48 和 IR88–122
- 配置写入后立即校验、持久化并回读
- 阀门配置使用上、左、右三路“空闲位置”，不再提供“初始路由”和“上电初始位置”
- 最新时间单位：流量无变化报警、除湿运行周期按“天”；停热后设备冷却、最长加热时间与防冻关闭延时按“小时”
- 多设备串口配置、采集会话记录和数据导出
- IEC61850 转发配置工作台：选择固件支持的 Modbus V10 源点，统一命名，探测 TCP 102，并生成内嵌 `sAddr` 映射的单一 CFG、点表和 ICD
- IEC61850 现场测试总站：导入 ICD，通过网口同时管理多台设备，显示中文点名、IEC 模型树、实时值、品质、数据集、URCB/GI、事件和在线模型比对

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

进入“设备管理”配置串口和从站地址，选择设备后点击“启动监控”。首次收到数据时会校验 FC04 地址 100 必须等于 `0x0A00`。

进入“61850总站”可导入 ICD、修改设备 IP 并连接 TCP 102。首次搭建源码环境时运行：

```powershell
python scripts\setup_iec61850_client_runtime.py
```

该脚本准备隔离的 32 位测试客户端运行时，不改变主程序的 Python 环境。当前开发机已经准备完成。

## 自动测试

```powershell
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check app\web\app.js
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check app\web\iec61850-config.js
& "C:\Users\MyPC\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" --check app\web\iec61850-station.js
```

## 打包

运行 `scripts\打包分析系统EXE.bat`。输出位于 `release\YLDQ6.0远程监控系统`。

## 结构

- `app/dashboard_server.py`：监控 HTTP API 和静态资源服务
- `app/live_acquisition_service.py`：多设备采集、控制、配置与记录
- `app/live_register_catalog.py`：Modbus V10唯一点表
- `app/iec61850_workspace.py`：IEC61850配置校验、点表筛选、网络探测和交付包生成
- `app/iec61850_station.py`：ICD解析、多设备连接、模型比对、实时值和报告会话管理
- `app/iec61850_worker.py`：隔离运行的32位libiec61850客户端工作进程
- `app/modbus_v10_codec.py`：寄存器类型编解码
- `app/modbus_v10_config.py`：配置写入及持久化确认
- `app/monitoring_projection.py`：界面监控模型
- `app/web/`：最终监控界面
- `tests/`：协议、采集、投影和记录测试
- `docs/design/`：架构设计
