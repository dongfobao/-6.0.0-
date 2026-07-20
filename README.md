# YLDQ 本地数据分析系统

这是本地运行的数据分析系统，用于读取设备导出的环境日志、呼吸日志、运行日志和配置文件，生成可交互的趋势图、诊断结果、参数建议和参数模拟结果。

## 快速使用

双击根目录脚本：

- `启动分析系统.bat`：启动本地网页系统，默认地址 `http://127.0.0.1:8765`
- `打包分析系统EXE.bat`：打包完整分析系统工作台
- `生成客户版报告.bat`：生成客户交付静态报告
- `打包客户交付版EXE.bat`：打包客户交付版程序

## 目录结构

- `app/`：主程序源码，包含 Python 后端和 `web/` 前端资源。
- `scripts/`：启动、打包、生成报告等辅助脚本。
- `packaging/`：PyInstaller 打包配置。
- `tests/`：单元测试。
- `docs/`：设计文档和客户说明。
- `release/`：已打包的可执行程序和压缩包。
- `实时采集会话/`：现场采集会话数据。

## 数据目录约定

运行源码版本时，程序默认读取根目录下的 `实时数据/`：

- `实时数据/config.json`
- `实时数据/data_0/log_*.csv`
- `实时数据/breath_data/breath_*.csv`
- `实时数据/run/*.csv`

打包后的 EXE 会读取 EXE 同级目录下的 `实时数据/`。

## 开发验证

```bat
python -m py_compile app\*.py
python -m unittest discover tests
node --check app\web\app.js
```

`build/` 和 `dist/` 是 PyInstaller 中间目录，可以删除；`release/` 是交付输出，应保留。

# -6.0.0-
