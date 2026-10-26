# -*- coding: utf-8 -*-
"""钻孔 D1-D3 现场操作台。

入口：
    python code/pc/drill_console.py
    run_drill_test.bat

流程：
    TZ -> TE -> D1 -> D2 -> D3 -> Q
    FULL / RUN = D1 + D2 + D3
    DC = 只跑钻孔核心

配置：
    config/drill_params.json
    config/safe_z.json / drill_start_z.json / electrode_calibration.json
运行后更新的值写到 runtime/drill_state.json，不修改 config 初始值。
"""

import argparse
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from serial_motion import (
    BAUD, pick_port, open_verified_arduino, send, read_response,
    query_positions, wait_positions, normalize_motion_command,
)
from turntable import Turntable, handle_turntable
from force_sensor import ForceSensor, load_config as load_sensor_config
from settings import TURNTABLE_PORT, TURNTABLE_BAUD
from vision_workflows import run_automatic_vision, run_visual_head
import serial_motion as motion
import drill_workflows as wf


def connect_turntable():
    try:
        tt = Turntable(TURNTABLE_PORT, TURNTABLE_BAUD)
        print(f'转盘已连接 {TURNTABLE_PORT} @ {TURNTABLE_BAUD}')
        return tt
    except Exception as exc:
        print(f'转盘未连接（{exc}）；D1/D2/D3 不可用，手动运动仍可用')
        return None


def read_force_once():
    try:
        sensor = ForceSensor(config=load_sensor_config())
        sensor.start()
        deadline = time.monotonic() + 2.0
        while sensor.latest() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        sample = sensor.latest()
        print(f'力值: {sample}' if sample is not None else f'传感器无数据（{sensor.last_error}）')
        sensor.close()
    except Exception as exc:
        print(f'传感器读取失败：{exc}')


def show_force_live(seconds=5.0):
    try:
        sensor = ForceSensor(config=load_sensor_config())
        sensor.start()
        values = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            sample = sensor.latest()
            if sample is not None:
                values.append(sample[1])
                print(f'\r  raw={sample[1]:>10} value={sample[2]:>12.3f}   ', end='', flush=True)
            time.sleep(0.15)
        print()
        if values:
            print(f'  min={min(values)} max={max(values)} 变化={max(values) - min(values)}')
        sensor.close()
    except Exception as exc:
        print(f'传感器读取失败：{exc}')


def _state_text():
    s = wf.load_state()
    p = wf.load_params()
    te, td = wf.tools_from_config()
    return (
        f"SAFE={s['safe_z_steps']} DRILL_START={s['drill_start_z']} "
        f"OFFSET={s['offset_steps']:+d} INSERT={s['insert_steps']:+d} "
        f"Z_STOP={wf.get_zstop()} TOOLS=T{te}/T{td} "
        f"duty={p.drill_duty} depth={p.safe_depth_steps} lift={p.lift_steps}"
    )


def print_help():
    print("""
================ 钻孔 D1-D3 操作台 ================
手动：
  X100 / Y-50 / Z200 / B10      相对移动（Z+ 向下）
  G0 X1000 Y2000 Z500           绝对步数
  M0 X50 Y30 Z10                绝对毫米
  POS / P                       查询坐标
  SPEED500                      设置速度
  HOME / HX / HY / HZ           回零（Z -> Y -> X）
  ZERO / R                      坐标清零（不移动）
  VISION / VIS                  归零→视觉识别→移动目标 XY
  VIS_FAST / VISF               已确认零点时跳过归零，视觉识别
  VIS_HEAD                      归零并识别头部 4 点
  VIS_HEAD_FAST / VIS_HEADF     跳过归零，再次识别头部
  A [N]                         快速下降，不转钻头（默认 500 步）
  DRILL OFF / STATUS            关钻头/状态
  TZ / TE / TD                  转盘设零/使能/失能
  T1 / T2 / T3 / TN / TP        工具位
  F / S                         力值一次/实时 5 秒
  E / STOP                      急停
  Q                             退出
流程：
  D1 / DRILLSTAGE               阶段1：安全→T2→钻孔核心→抬升
  D2 / SWAP                     阶段2：安全→T1
  D3 / ELECTRODE                阶段3：电极按 Z_STOP+offset+insert 下探
  FULL / RUN                    D1→D2→D3
  DC                            只跑钻孔核心
标定：
  SAFE / SAFE <Z>               查看/设置安全高度
  DRILLSTART / DRILLSTART <Z>   查看/设置钻孔起点
  ZSTOP / ZSTOP <Z>             查看/设置本会话 Z_STOP
  OFFSET / OFFSET <steps>       查看/设置电极 offset
  INSERT / INSERT <steps>       查看/设置额外下压
  ECAL                          电极接触标定（1mm 步进）
==================================================
""")


def _manual(ser, line):
    up = line.strip().upper()
    if up in ('HOME', 'HX', 'HY', 'HZ'):
        markers = {
            'HOME': ('HOME DONE', 'FAIL'),
            'HX': ('HOMED X', 'FAIL'),
            'HY': ('HOMED Y', 'FAIL'),
            'HZ': ('HOMED Z', 'FAIL'),
        }
        send(ser, up)
        out = read_response(ser, markers=markers[up], timeout=120)
        print(out, end='')
        if 'FAIL' in (out or ''):
            print(f'{up}: 回零失败，请检查限位/接线')
        if up == 'HOME':
            motion.vision_reference_ready = 'HOME DONE' in (out or '') and 'FAIL' not in (out or '')
        else:
            motion.vision_reference_ready = False
        return True
    if up in ('ZERO', 'R'):
        send(ser, up)
        print(read_response(ser, timeout=0.5), end='')
        motion.vision_reference_ready = False
        return True
    if up in ('POS', 'P') or re.fullmatch(r'[XYZB]\s*-?\d+', up) or up.startswith(('G0', 'M0')):
        cmd = normalize_motion_command(line)
        send(ser, cmd)
        print(read_response(ser, timeout=0.5), end='')
        return True
    if up == 'SPEED' or up.startswith('SPEED'):
        send(ser, line)
        print(read_response(ser, timeout=0.5), end='')
        return True
    if up in ('DRILL OFF', 'DRILL STATUS'):
        send(ser, up)
        print(read_response(ser, timeout=0.5), end='')
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description='钻孔 D1-D3 现场操作台')
    parser.add_argument('--serial-port', help='Arduino 串口（默认自动识别）')
    args = parser.parse_args()

    port = args.serial_port or pick_port()
    try:
        ser = open_verified_arduino(port)
    except RuntimeError as exc:
        print(f'Arduino 连接失败：{exc}')
        return
    print(f'Arduino 已连接 {port} @ {BAUD}')
    tt = connect_turntable()
    print(_state_text())
    print_help()

    try:
        while True:
            try:
                line = input('drill> ').strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            up = line.upper()
            if up in ('Q', 'QUIT', 'EXIT'):
                break
            if up == '?':
                print_help()
                continue
            if up in ('FULL', 'RUN'):
                if input('确认开始 FULL？(y/N): ').strip().lower() != 'y':
                    print('已取消')
                    continue
                wf.run_full(ser, tt)
                continue
            if up in ('D1', 'DRILLSTAGE'):
                wf.drill_stage(ser, tt)
                continue
            if up in ('D2', 'SWAP'):
                wf.swap_stage(ser, tt)
                continue
            if up in ('D3', 'ELECTRODE', 'ELE'):
                wf.electrode_stage(ser, tt)
                continue
            if up == 'DC':
                wf.run_automatic_drill(ser)
                continue
            if up == 'ECAL':
                wf.ecal(ser, tt)
                continue
            if up.startswith('SAFE'):
                text = line[4:].strip()
                if text:
                    try:
                        wf.set_safe_z(int(text))
                    except ValueError:
                        print('SAFE 需要整数步数')
                else:
                    print(f"SAFE_Z={wf.load_state()['safe_z_steps']}")
                continue
            if up.startswith('DRILLSTART'):
                text = line[10:].strip()
                if text:
                    try:
                        wf.set_drill_start(int(text))
                    except ValueError:
                        print('DRILLSTART 需要整数步数')
                else:
                    print(f"DRILL_START_Z={wf.load_state()['drill_start_z']}")
                continue
            if up.startswith('ZSTOP'):
                text = line[5:].strip()
                if text:
                    try:
                        wf.set_zstop(int(text))
                    except ValueError:
                        print('ZSTOP 需要整数步数')
                else:
                    print(f'Z_STOP={wf.get_zstop()}')
                continue
            if up.startswith('OFFSET'):
                text = line[6:].strip()
                if text:
                    try:
                        wf.set_offset(int(text))
                    except ValueError:
                        print('OFFSET 需要整数步数')
                else:
                    print(f"OFFSET={wf.load_state()['offset_steps']:+d}")
                continue
            if up.startswith('INSERT'):
                text = line[6:].strip()
                if text:
                    try:
                        wf.set_insert(int(text))
                    except ValueError:
                        print('INSERT 需要整数步数')
                else:
                    print(f"INSERT={wf.load_state()['insert_steps']:+d}")
                continue
            if up in ('E', 'STOP'):
                send(ser, 'STOP')
                print(read_response(ser, timeout=1.0), end='')
                continue
            if up == 'F':
                read_force_once()
                continue
            if up == 'S':
                show_force_live()
                continue
            if up in ('VISION', 'VIS'):
                run_automatic_vision(ser)
                continue
            if up in ('VIS_FAST', 'VISF'):
                run_automatic_vision(ser, skip_home=True)
                continue
            if up == 'VIS_HEAD':
                run_visual_head(ser)
                continue
            if up in ('VIS_HEAD_FAST', 'VIS_HEADF'):
                run_visual_head(ser, skip_home=True)
                continue
            match = re.fullmatch(r'A\s*(\d*)', up)
            if match:
                steps = int(match.group(1)) if match.group(1) else 500
                pos = query_positions(ser)
                if pos is None:
                    print('读取 POS 失败')
                    continue
                print(f'接近：Z={pos["Z"]} -> {pos["Z"] + steps}（钻头不转）')
                if input('确认？(y/N): ').strip().lower() != 'y':
                    print('已取消')
                    continue
                send(ser, 'SPEED 500')
                read_response(ser, timeout=0.3)
                send(ser, f'Z {steps}')
                read_response(ser, timeout=0.3)
                ok = wait_positions(ser, {'Z': pos['Z'] + steps}, timeout=30)
                print(f'接近{"完成" if ok else "未确认"}，POS={query_positions(ser)}')
                continue
            if up.startswith('T'):
                if tt is None:
                    print('转盘未连接')
                elif not handle_turntable(tt, line):
                    print('未知转盘命令（TZ/TE/TD/T1/T2/T3/TN/TP）')
                continue
            if _manual(ser, line):
                continue
            print('不支持的命令（? 查看帮助）')
    finally:
        try:
            send(ser, 'E')
            read_response(ser, timeout=0.5)
        except Exception:
            pass
        if tt is not None:
            try:
                tt.close()
            except Exception:
                pass
        try:
            ser.close()
        except Exception:
            pass
        print('已退出（E 已发送）')


if __name__ == '__main__':
    main()
