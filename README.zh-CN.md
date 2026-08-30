# RoboForge 🤖

[English](README.md) | **中文**

![version](https://img.shields.io/badge/version-v0.1--alpha-blueviolet)
![status](https://img.shields.io/badge/status-起步版本·持续完善中-orange)

**让大模型看着现场情况，现场写代码驱动机器人。**

> 📌 **项目状态**：这是 RoboForge 的 **v0.1 起步版本**（alpha）。核心闭环已经
> 打通并通过全部测试，但距离完善还有很长的路——真机固件要按底盘适配、
> 感知要标定、技能库检索要升级成语义检索、语音输入、更多机器人形态
> （机械臂、足式）都在计划里。**它会持续不断地完善**，欢迎 star、提 issue、
> 一起改进。
>
> ✍️ **作者**：一名大一学生（关于我，见本账号主页简介）。这个项目源于一个
> 想法："机器人能不能不靠人写代码，自己看着现场情况、现场写代码解决问题？"
> 如果你也是学生，这个项目想告诉你：你现在就能动手做出你认为只有大公司
> 才做得出来的东西。

RoboForge is a lightweight, open-source implementation of the
"code-as-policies" idea: instead of hard-coding robot behaviors, an LLM
watches the scene and **writes a Python skill on the fly**, which is
sandboxed, safety-checked, verified, then executed — and cached into a
skill library so similar tasks are later answered with **zero model
calls**. The same generated skill runs in simulation, on a $20 ESP32
over WiFi, on an STM32 over serial, or inside a ROS 2 stack.

> 你不需要写任何机器人代码。你只需要用一句话描述任务。

```
=== Task: 把红色方块 red_box 送到右上角的目标区 ===
[brain] attempt 1: asking the model to write a skill...
  [skill] found red_box at 5.0 3.0
  [skill] carrying red_box
  [skill] delivered red_box to [8.0, 8.0]
[brain] success check PASSED
[brain] verified and saved as skill_001
Result: SUCCESS (attempts=1, source=mock, skill=skill_001)

# 第二次运行同一任务：
Result: SUCCESS (attempts=1, source=library, skill=skill_001)   ← 零模型调用
```

## 它是怎么工作的

```
        ┌─────────────────────────────────────────────────────┐
        │  你："把红色方块送到右上角"（打字，未来可接语音）          │
        └───────────────────────┬─────────────────────────────┘
                                ▼
                 ① 技能库查找（已验证技能直接复用）
                                ▼ 未命中
                 ② LLM 现场生成技能代码  def run(robot): ...
                                ▼
                 ③ 沙箱执行 —— 白名单代理 + 禁止 import/IO，
                    看门狗线程掐死死循环
                                ▼
                 ④ 安全层 —— 速度/目标点/时长硬限制，
                    模型永远碰不到这一层
                                ▼
                 ⑤ 执行 —— 通过硬件抽象层(HAL)到达任何载体
                                ▼
                 ⑥ 技能库 —— 验证过的代码缓存复用，越用越快
```

关键设计原则：**模型只负责"写"，从不负责"保证"**。生成的代码是概率性的，
所以每一层都有确定性护栏：沙箱限制它能动什么，安全层限制它能去哪里，
HAL 保证同一段代码在仿真和真机上行为一致。

## 连接真实机器人

所有载体实现同一个 [HAL 接口](robocode/backends/__init__.py)，对话时用
`--backend` 选择，同一段生成的技能代码不改一行：

```bash
python main.py --chat --backend sim                                  # 仿真
python main.py --chat --backend serial --port COM3                   # USB/串口
python main.py --chat --backend serial --port /dev/ttyUSB0           # Linux 串口
python main.py --chat --backend http   --base-url http://192.168.4.1 # WiFi 机器人
python main.py --chat --backend ros2                                 # ROS 2 机器人
```

| 后端 | 适用 | 依赖 |
|---|---|---|
| `sim` | 内置 2D 仿真，零成本试验 | 无（纯标准库） |
| `serial` | Arduino / ESP32 / STM32 串口底盘 | 真机需 `pip install pyserial` |
| `http` | ESP32 等 WiFi 机器人（REST 控制） | 无 |
| `ros2` | TurtleBot 等行业标准栈 | 机器人上有 ROS 2 |

**机器人"身体"那边**：`firmware/` 提供参考固件和一份协议规范
[PROTOCOL.md](firmware/PROTOCOL.md)（JSON-lines 串口协议 + HTTP 路由）——

- `firmware/arduino_roboforge_rhp1.ino` —— Arduino/ESP32 串口固件（100Hz 控制环、斜坡限速、500ms 看门狗、急停）
- `firmware/esp32_http_server.ino` —— ESP32 WiFi 固件（REST 路由）
- `firmware/stm32_keil_main.c` —— STM32/Keil MDK 模板（含 CubeMX 集成说明）

固件侧必须自带的保护：看门狗（大脑静默 500ms 自动停）、速度斜坡、
硬件急停、编码器里程计。**PC 侧安全层是第二道防线，永远不能替代固件护栏。**

**机器人"眼睛"**（真机感知，`robocode/vision.py`）：三种来源，输出同一格式

- `StaticMapVision` —— 操作员标定的物体表（先跑起来）
- `VLMVision` —— 摄像头帧 + 多模态大模型（GLM / Qwen-VL / 任意 OpenAI 兼容接口）实时识别物体坐标（需 `opencv-python`）
- 仿真里自动用完美感知

## 快速开始

零依赖（纯 Python 标准库，Python ≥ 3.10）：

```bash
# 离线演示：内置 mock 模型，不需要任何 API key
python main.py --demo --map

# 跑测试（含假固件协议一致性、真实 HTTP 服务器集成测试）
python -m unittest discover tests -v

# 压力测试：40 个对抗技能轰炸沙箱 + 150 次随机任务 + CLI 连跑
python scripts/stress_test.py
```

接真实大模型（GLM / DeepSeek / 任何 OpenAI 兼容接口）：

```bash
cp config.example.json config.json   # 填入 api_key
python main.py --chat                # 对话模式：说话→思考→写代码→执行
```

`config.json`：

```json
{
  "provider": "openai",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key": "你的key",
  "model": "glm-5.3-flash",
  "backend": {"type": "sim"},
  "work_area": [10.0, 10.0]
}
```

## 项目结构

```
robocode/
  simulator.py     2D 物理仿真：差速机器人、障碍物、可推动的物体
  backends/        硬件抽象层：sim / serial / http / ros2 四种载体
  robot_api.py     RobotAPI —— 生成代码唯一能调用的接口
  safety.py        硬安全层：限速/限区/限时，硬编码常量
  sandbox.py       沙箱：白名单代理、禁止 import/下划线、超时击杀
  vision.py        感知：仿真/静态标定/摄像头+VLM
  codegen.py       LLM 客户端（OpenAI 兼容接口 + 内置 mock）
  skill_library.py 技能库：验证通过的技能缓存与检索
  brain.py         总编排：查库 → 生成 → 沙箱 → 验证 → 入库
  chat.py          对话界面
firmware/          RHP1 协议规范 + Arduino/ESP32/STM32 参考固件
tests/             单元测试 + 后端一致性测试（假固件/真HTTP）
scripts/           压力测试与对抗测试
```

## 已知边界（诚实声明）

- 真机固件是参考实现：引脚映射、编码器、夹爪需要按底盘适配；
  协议本身有一致性测试兜底（测试里的假固件说的就是 PROTOCOL.md 这套话）。
- VLM 感知需要标定（像素→米），识别精度取决于相机和模型。
- 技能库检索是词法匹配（英文按词、中文按字）；换 embedding 检索是明显的下一步。
- 仿真验证通过 ≠ 真机成功。真机部署请务必保留固件看门狗与急停。

## 类似项目

- [google-research/code-as-policies](https://github.com/google-research/code-as-policies) —— 本项目思路的源头（ICRA 2023）
- VoxPoser、GenSwarm 等 —— LLM 生成机器人控制程序的后续研究

## 路线图（会持续完善）

- [x] v0.1：核心闭环（生成 → 沙箱 → 安全 → 执行 → 技能库）+ HAL 四载体 + 对话界面
- [ ] v0.2：技能库语义检索（embedding）、语音输入/播报、Web 可视化面板
- [ ] v0.3：机械臂原语（pick/place 全流程）、多机器人协作
- [ ] v0.4：足式机器人原语（四足/人形）、真机社区固件合集

## License

MIT
