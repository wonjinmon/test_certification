#!/usr/bin/env python
import sys
import os

# --------------------------
# 간단한 BVH 파서 (계층 + 채널 인덱스만 필요)
# --------------------------

class Joint:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent
        self.children = []
        self.offset = (0.0, 0.0, 0.0)
        self.channels = []        # 예: ["Xposition","Yposition","Zposition","Yrotation","Xrotation","Zrotation"]
        self.chan_start = -1      # 모션 배열에서 이 조인트의 첫 채널 인덱스

    def __repr__(self):
        return f"Joint({self.name}, ch={len(self.channels)}, start={self.chan_start})"


class BVH:
    def __init__(self, text):
        self.text = text
        self.root = None
        self.joints_by_name = {}
        self.frames = 0
        self.frame_time = 0.0
        self.motion = []          # List[List[float]]
        self.total_channels = 0
        self._parse()

    def _parse(self):
        # 공백 라인 제거 + strip
        lines = [ln.strip() for ln in self.text.splitlines() if ln.strip() != ""]
        if not lines or not lines[0].upper().startswith("HIERARCHY"):
            raise ValueError("BVH 파일이 아니거나 HIERARCHY 헤더가 없습니다.")
        i = 1

        channel_cursor = 0

        def parse_joint_block(joint, idx):
            nonlocal channel_cursor
            if lines[idx] != "{":
                raise ValueError(f"조인트 {joint.name} 블록에서 '{{'를 기대했으나: {lines[idx]}")
            idx += 1
            while idx < len(lines):
                ln = lines[idx]
                if ln.startswith("OFFSET"):
                    parts = ln.split()
                    nums = list(map(float, parts[1:4]))
                    joint.offset = tuple(nums)
                    idx += 1
                elif ln.startswith("CHANNELS"):
                    parts = ln.split()
                    n = int(parts[1])
                    joint.channels = parts[2:2 + n]
                    joint.chan_start = channel_cursor
                    channel_cursor += n
                    idx += 1
                elif ln.startswith("JOINT"):
                    # 자식 조인트
                    name = ln.split()[1]
                    child = Joint(name, joint)
                    joint.children.append(child)
                    self.joints_by_name[name] = child
                    idx += 1
                    idx = parse_joint_block(child, idx)
                elif ln.startswith("End Site"):
                    # End Site 블록 건너뛰기
                    idx += 1  # "End Site"
                    if lines[idx] != "{":
                        raise ValueError("End Site 뒤에 '{' 필요")
                    idx += 1
                    if not lines[idx].startswith("OFFSET"):
                        raise ValueError("End Site 블록에 OFFSET 필요")
                    idx += 1
                    if lines[idx] != "}":
                        raise ValueError("End Site 블록 종료 '}' 필요")
                    idx += 1
                elif ln == "}":
                    idx += 1
                    return idx
                else:
                    # 모르는 라인은 그냥 넘김
                    idx += 1
            return idx

        # ROOT
        if not lines[i].startswith("ROOT"):
            raise ValueError("HIERARCHY 다음에 ROOT가 나와야 합니다.")
        root_name = lines[i].split()[1]
        i += 1
        self.root = Joint(root_name, None)
        self.joints_by_name[root_name] = self.root
        i = parse_joint_block(self.root, i)

        # MOTION 섹션
        if not lines[i].startswith("MOTION"):
            raise ValueError("MOTION 섹션을 찾을 수 없습니다.")
        i += 1
        if not lines[i].startswith("Frames:"):
            raise ValueError("Frames: 라인을 찾을 수 없습니다.")
        self.frames = int(lines[i].split()[1])
        i += 1
        if not lines[i].startswith("Frame Time:"):
            raise ValueError("Frame Time: 라인을 찾을 수 없습니다.")
        self.frame_time = float(lines[i].split()[2])
        i += 1

        self.total_channels = channel_cursor

        # 각 프레임 모션 데이터
        self.motion = []
        for f in range(self.frames):
            if i + f >= len(lines):
                raise ValueError(f"프레임 {f} 데이터를 읽는 중 파일이 끝났습니다.")
            vals = list(map(float, lines[i + f].split()))
            if len(vals) != self.total_channels:
                raise ValueError(
                    f"Frame {f} 채널 수 불일치: {len(vals)}개, 기대값 {self.total_channels}"
                )
            self.motion.append(vals)


# --------------------------
# 마지막 프레임 각도 덮어쓰기 로직
# --------------------------

def apply_angle_patch(bvh: BVH, joint_names):
    """
    joint_names 에 포함된 조인트들의 '회전 채널(X/Y/Zrotation)'에 대해
    마지막 프레임 값을 2번째 프레임(인덱스 1) 값으로 덮어쓴다.
    """
    if bvh.frames < 2:
        raise ValueError("프레임이 2개 미만입니다. (2번째 프레임이 존재하지 않음)")

    start_idx = 1               # 두 번째 프레임 (0-based)
    end_idx = bvh.frames - 1    # 마지막 프레임

    start_frame = bvh.motion[start_idx]
    end_frame = bvh.motion[end_idx]

    for name in joint_names:
        j = bvh.joints_by_name.get(name)
        if j is None:
            print(f"[경고] 조인트 '{name}' 를 찾을 수 없습니다. (무시)")
            continue

        if j.chan_start < 0 or not j.channels:
            print(f"[경고] 조인트 '{name}' 에 채널이 없습니다. (무시)")
            continue

        base = j.chan_start
        for k, ch in enumerate(j.channels):
            # 회전 채널만 수정
            if "rotation" in ch:
                src_val = start_frame[base + k]
                end_frame[base + k] = src_val

    # 수정된 마지막 프레임을 되돌려 넣기
    bvh.motion[end_idx] = end_frame


def write_bvh_with_new_motion(original_text: str, bvh: BVH, out_path: str):
    """
    원본 텍스트에서 HIERARCHY 부분은 그대로 쓰고,
    MOTION 이후부터는 BVH 객체의 frames / frame_time / motion 데이터를 사용해 다시 쓴다.
    """
    raw_lines = original_text.splitlines(keepends=True)

    # MOTION 라인 위치 찾기
    motion_idx = None
    for i, ln in enumerate(raw_lines):
        if ln.strip().upper().startswith("MOTION"):
            motion_idx = i
            break

    if motion_idx is None:
        raise ValueError("원본 텍스트에서 MOTION 라인을 찾을 수 없습니다.")

    header_lines = raw_lines[:motion_idx]  # HIERARCHY ~ JOINT 정의 부분
    # 이후 내용은 모두 새로 작성

    with open(out_path, "w", encoding="utf-8") as f:
        # 헤더 그대로 출력
        f.writelines(header_lines)

        # MOTION 헤더
        f.write("MOTION\n")
        f.write(f"Frames: {bvh.frames}\n")
        f.write(f"Frame Time: {bvh.frame_time:.6f}\n")

        # 모션 프레임들
        for frame_vals in bvh.motion:
            line = " ".join(f"{v:.6f}" for v in frame_vals)
            f.write(line + "\n")


# --------------------------
# main
# --------------------------

def main():
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python patch_bvh_angles.py input.bvh --RightShoulder --RightElbow ...")
        sys.exit(1)

    bvh_path = sys.argv[1]
    if not os.path.isfile(bvh_path):
        print(f"BVH 파일을 찾을 수 없습니다: {bvh_path}")
        sys.exit(1)

    # '--조인트이름' 형식의 인자를 모두 모음
    joint_names = []
    for arg in sys.argv[2:]:
        if arg.startswith("--") and len(arg) > 2:
            joint_names.append(arg[2:])

    if not joint_names:
        print("[주의] 수정할 조인트 이름이 없습니다. 예: --RightShoulder --RightElbow")
        print("       파일을 그대로 복사하지 않고 종료합니다.")
        sys.exit(1)

    with open(bvh_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    bvh = BVH(text)

    print(f"[정보] 프레임 수: {bvh.frames}, 채널 수: {bvh.total_channels}")
    print(f"[정보] 패치 대상 조인트: {', '.join(joint_names)}")

    apply_angle_patch(bvh, joint_names)

    base, ext = os.path.splitext(bvh_path)
    out_path = base + "_patched" + ext

    write_bvh_with_new_motion(text, bvh, out_path)

    print(f"[완료] 패치된 BVH 저장: {out_path}")


if __name__ == "__main__":
    main()
