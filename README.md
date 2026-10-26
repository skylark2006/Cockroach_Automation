# Cockroach Automation

蟑螂自动化装配系统当前在用版本的整理目录。运动入口是 `code/pc/motion_client.py`；此目录从原 `pc/motion_client.py` 拆分，控制流程、参数和安全判断保持原样。

## 目录

| 路径 | 内容 |
| --- | --- |
| `code/pc/motion_client.py` | 启动入口、命令界面、点动和退出停机 |
| `code/pc/serial_motion.py` | Arduino 串口协议、运动、回零和位置确认 |
| `code/pc/turntable.py` | USB-CAN 转盘控制 |
| `code/pc/vision_workflows.py` | 腹部和头部视觉流程、坐标换算及运动检查 |
| `code/pc/settings.py` | 串口、相机、运动和安全参数 |
| `code/vision/` | 视觉识别与标定源码 |
| `config/` | 当前流程实际读取的标定与点位补偿 JSON |
| `firmware/` | Arduino 运动固件源码 |
| `tools/rs485/source/` | RS485 工具源码、构建脚本和独立依赖清单 |
| `tools/rs485/release/` | RS485 已发布 EXE 和使用说明 |
| `tools/camera/`、`tools/diagnostics/` | 相机与矩阵检查工具 |
| `hardware/ip42/` | IP42 驱动器手册、接线图和完整调试软件 |
| `runtime/` | 运行时生成的日志和识别结果，不提交 Git |
| `tests/` | 无硬件自动检查及独立的转盘手动检查脚本 |
| `docs/` | 第三方源码许可证及不参与运行的点位记录 |

## 代码文件用途

**`code/pc/`（上位机与运动控制）**

- `motion_client.py`：主程序，接收命令、进入点动模式，调用各控制模块，退出时发送停机命令。运行它即可；原来的 `cli.py` 已合并到这里。
- `serial_motion.py`：Arduino 串口连接与固件核验、命令发送、位置读取、回零及连续运动。视觉流程也通过它读写运动状态。
- `turntable.py`：USB-CAN 转盘使能、设零点、换工具和位置保持。主程序会调用它。
- `DM_CAN.py`：转盘电机通信所依赖的驱动源码；不能仅因主程序没有直接导入就删除。
- `vision_workflows.py`：腹部和头部视觉任务的流程控制、坐标换算和移动前检查。
- `vis_head.py`：头部点位的实际图像识别，由 `vision_workflows.py` 调用。
- `xy_coordinate_transform.py`：像素坐标转机械 XY 坐标，由视觉流程调用。
- `settings.py`：串口、相机、运动和安全阈值，以及各配置文件路径。换电脑时优先核对这里。

**`code/vision/`（图像处理）**

- `abdomen_spot_detector.py`：腹部图像中的候选点识别。
- `head.py`：头部点位图像识别，被 `vis_head.py` 调用。
- `live_abdomen_detection.py`：相机采集、多帧腹部识别及结果预览，被自动视觉流程调用。
- `calibrate_xy_from_images.py`：用标定图像重新计算像素到机械坐标的矩阵；正常运行主程序时不调用。

视觉模块原有的独立依赖清单与根目录 `requirements.txt` 重复，因此整理版只保留根目录的一份。

`tests/manual_turntable/` 的三个脚本是分步骤验证转盘使能、转动及三个工具位的**手动硬件检查**，主程序不依赖它们；不要在无人监护时运行。`tests/test_motion_safety.py` 是不接设备的自动检查，方便改动后确认关键保护仍在。`tests/` 对实际运行不是必需，但建议随源码保留。

`docs/DM_Control_Python_LICENSE` 是 `DM_CAN.py` 上游源码的 MIT 许可文本。上传 GitHub 分享源码时应保留；它不参与程序运行。`docs/reference/vision_position.json` 记录了旧机位测量信息，当前程序不读取它；实际运行参数在 `settings.py`。

## 安装与运行

在 Windows 上安装 Python 3.11 或兼容版本，然后在本目录执行：

```powershell
python -m pip install -r requirements.txt
python code/pc/motion_client.py
```

RS485 工具使用独立依赖：`tools/rs485/source/requirements.txt`。已经构建的程序见 `tools/rs485/release/`；接线与操作先看该目录的说明。Arduino 固件需单独烧录，且上位机会验证固件标识。运行前按实际电脑检查 `code/pc/settings.py` 的串口、相机和运动参数，以及 `config/` 中的标定数据。

`motion_client.py` 退出时仍会向 Arduino 发送安全停止指令。首次接入实体设备时，请在操作员监护下确认串口和当前位置；自动视觉移动依赖实际机械回零、位置反馈及标定。

## 测试

不连接设备时可运行：

```powershell
python -m unittest discover -s tests -v
```

相机、Arduino 和转盘的真实连接与运动尚需在设备上验证。

## 来源说明

`code/pc/DM_CAN.py` 来源于目录外原有的 `pc/DM_CAN.py`。其上游项目的许可证副本见 `docs/DM_Control_Python_LICENSE`。原目录中的历史日志、调试图像、缓存、相机探测依赖副本和旧版本未纳入此整理目录。

## 钻孔 D1-D3

- 入口：`python code/pc/drill_console.py`，或双击 `run_drill_test.bat`
- 流程：`TZ -> TE -> D1 -> D2 -> D3 -> Q`；`FULL` / `RUN` 执行三阶段；`DC` 只跑钻孔核心
- 配置：`config/drill_params.json`（工具映射、进给、限深、抬升、`drill_duty`、ECAL、D3 速度）
- 标定初始值：`config/safe_z.json`、`config/drill_start_z.json`、`config/electrode_calibration.json`
- 运行状态：`runtime/drill_state.json`，程序生成，不修改 config
- 当前：T1=电极、T2=钻孔，`drill_duty=0`（D1 下 Z、钻头不转），限深 2500 步，抬升 2000 步，D3 速度 500 步/秒
- `Z_STOP` 每次 D1 更新；视觉与转盘原功能保留，`motion_client.py` 的 `DC` 复用同一钻孔核心
- D1/DC 运行时 `run_drill_test.bat` 会自动弹出 `tools/drill_plot/force_plot.py` 实时力曲线窗口；它只读 CSV，不占用传感器串口
