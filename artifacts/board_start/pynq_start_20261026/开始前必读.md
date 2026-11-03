# PYNQ-Z2 首次上板：仅 USB 与电脑

这份流程只做一次可回退的 FPGA 推理验证：不刷卡、不格式化、不写 QSPI、不更新系统、不修改开机服务，也不需要 HDMI 显示器。结果会写到 SD 卡的 FAT 启动分区，关机后插回电脑读取。

## 绝对不要做的事

- 不要打开 balenaEtcher 后点击 Flash；它会整盘覆盖 MicroSD 卡。
- 不要在 Windows 弹出“需要格式化此驱动器”时格式化。Windows 看不到 Linux 分区是正常的。
- 不要删除或覆盖 E 盘根目录的 `BOOT.BIN`、`image.ub`、`boot.scr`、`boot.py`、`REVISION`。
- 不要在板端执行 `pip install`、`apt upgrade`、`systemctl enable`、`systemctl disable`、`systemctl daemon-reload` 或写入 QSPI 的命令。
- 不要把板子的 HDMI OUT 接到笔记本 HDMI 口；笔记本 HDMI 通常是输出口，不能当显示器。
- 断电或拔卡前必须先执行 `sudo shutdown -h now`，等串口没有新输出、DONE 灯熄灭后，再拨电源开关并取卡。

现有 E 盘启动文件已经备份到开发电脑项目的 `artifacts/board_start/boot_files_backup_20261026`。这不是整张卡的完整镜像；如果未来确实要刷卡，先另做完整磁盘镜像并征得负责人同意。

## 你需要的东西

- PYNQ-Z2、其现有 MicroSD 卡。
- 一根确认能传数据的 Micro USB 线。
- Windows 电脑和 PuTTY。
- 本目录随测试包提供的 `pynq_start_20261026.zip`。

Vivado、Vitis Model Composer 和 balenaEtcher 此次均不使用。

## 连接前的硬件检查

所有连接和跳线调整都在断电状态完成。

1. 保持 MicroSD 卡插在板背面的卡槽中。
2. 将标为 **BOOT** 的跳帽放到 **SD** 一侧。
3. 将靠近电源开关的 **J9 / POWER** 跳帽放到 **USB** 一侧，因为这次从电脑 Micro USB 供电。
4. 只把 Micro USB 数据线连接到板上印有 **PROG UART** 的 Micro USB 接口，再接到电脑。不要接 USB HOST，也不要接 HDMI IN/OUT。
5. 合上电源开关。红色电源灯应立即点亮，随后 DONE 灯点亮。启动约需一分钟。

官方 PYNQ-Z2 设置说明也要求 SD 启动、USB 供电时 J9 置 USB，以及把电脑连接到 PROG-UART 接口。 [PYNQ-Z2 设置指南](https://pynq.readthedocs.io/en/v2.5/getting_started/pynq_z2_setup.html)

若 USB 供电时板子反复重启、串口断连或 DONE 灯不稳定，关闭电源并停止本轮测试。不要反复强行运行；待准备 12 V、中心正极、至少 2 A 的电源后，将 J9 改为 REG 再继续。

## 打开串口终端

1. Windows 打开“设备管理器” → “端口（COM 和 LPT）”，找到新出现的 USB Serial Port，例如 COM9。
2. 打开 PuTTY：选择 **Serial**；Serial line 填该 COM 号；Speed 填 **115200**。
3. 在 Connection → Serial 中确认 Data bits 8、Stop bits 1、Parity None、Flow control None，然后 Open。
4. 等待启动信息；若显示登录提示，用户名与密码均先尝试 `xilinx`。输入密码时屏幕不会显示字符，这是正常的。
5. 登录后先输入：

```bash
pwd
uname -m
```

预期当前目录类似 `/home/xilinx`，架构是 `armv7l`。串口参数来自 [PYNQ 官方入门说明](https://pynq.readthedocs.io/en/v2.2.1/getting_started.html)。

## 将测试包从 E 盘复制到板端

在 Windows 上先验证 ZIP 的 SHA256 与同目录 `.sha256` 文件一致。关闭所有正在打开 E 盘文件的窗口，使用“安全删除硬件”弹出 MicroSD 卡，再将卡重新插回板子。不要在板子通电时插拔卡。

板端登录后，复制启动分区中的 ZIP 到 Linux 主目录并解压。下面命令不修改 `/boot` 的启动文件，只在 `/home/xilinx` 创建一个新目录。

```bash
cd /home/xilinx
mkdir -p board_tests
cp /boot/pynq_start_20261026.zip board_tests/
cd board_tests
unzip -t pynq_start_20261026.zip
unzip pynq_start_20261026.zip
cd pynq_start_20261026
source board_env.sh
```

若 `cp /boot/...` 报“找不到文件”，先执行 `ls -l /boot`。不要猜测路径或在 `/boot` 中删除内容。

## 第一次：只做环境预检

```bash
"$BOARD_PY" board_test.py --preflight
```

预期最后一行是：

```text
PREFLIGHT_PASS (no bitstream loaded)
```

如果提示旧 `lesion-fpga.service` 正在运行，先只执行：

```bash
sudo systemctl stop lesion-fpga.service
sudo systemctl is-active lesion-fpga.service
```

预期第二条输出 `inactive`。这只停止当前运行的旧程序，重启后它会按原配置恢复；不要 disable 服务。然后重新执行预检。

## 第二次：单张 FPGA 对照

确认预检通过后，执行：

```bash
sudo env XILINX_XRT="$XILINX_XRT" PYTHONPATH="$PYTHONPATH" "$BOARD_PY" board_test.py --run --count 1
```

这一步会把**运行时** bitstream 下载到可编程逻辑；断电、重启或旧服务重新加载位流后会恢复，因此不会写 Flash。成功标准是最后出现 `ALL_PASS`，并且该图的 25 个网络张量、网络掩膜和最终原图掩膜均与电脑参考一致。

若出现 `TEST_FAILED`、`CASE_DIFFERENCE`、超时、黑屏、重启或串口断开：停止，不要重复运行；保留完整 PuTTY 输出并继续“取回结果”。

## 可选：三张小图

仅当第一张 `ALL_PASS` 后才运行：

```bash
sudo env XILINX_XRT="$XILINX_XRT" PYTHONPATH="$PYTHONPATH" "$BOARD_PY" board_test.py --run --count 3
```

其中包含横向、纵向及原先失败类型的缩小测试图，仍不会启动 HDMI。

## 导出结果、关机、取回卡

只有测试已运行且无异常时执行：

```bash
sudo env XILINX_XRT="$XILINX_XRT" PYTHONPATH="$PYTHONPATH" "$BOARD_PY" board_test.py --export-last
sudo shutdown -h now
```

等待串口不再输出、板子停止运行后，将电源开关拨到 OFF，再拔掉 USB 线和 MicroSD 卡。把卡插回电脑；E 盘根目录会出现一个 `pynq_result_*.zip`。复制这个 ZIP 到项目 `artifacts/board_start/results/`，不要直接删除卡上的文件。

如果导出命令失败，仍然执行 `sudo shutdown -h now`；卡上的 `/home/xilinx/board_tests/.../results` 不会因关机丢失。下次启动后可继续通过串口查看。不要为了取文件而在 Windows 格式化 Linux 分区。

## 成功后的下一步

把 `pynq_result_*.zip` 放回项目目录后，再进行 HDMI、鼠标、性能和稳定性验收。不要在首次对照成功前修改 systemd 自启动，也不要用大于测试包尺寸的原始 ISIC2018 图像做压力测试。
