"""cat vs dd into the pen device, with empty sync events only (no coordinates, no ink).
24.10.: cat died after 126 of 1500 reports ('write error: Invalid argument'), dd delivered all."""
import struct, subprocess, time
SYN = struct.pack("llHHi", 0, 0, 0, 0, 0)
for name, cmd in (("cat", "cat > /dev/input/event2"),
                  ("dd", "dd bs=24 iflag=fullblock of=/dev/input/event2 2>/dev/null")):
    p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "remarkable", cmd],
                         stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    sent, err = 0, ""
    try:
        for _ in range(1500):
            p.stdin.write(SYN * 3); p.stdin.flush(); sent += 1; time.sleep(0.002)
        p.stdin.close(); rc = p.wait(timeout=30)
    except Exception as e:
        err, rc = repr(e), p.poll()
    print(name, "sent", sent, "of 1500", "rc", rc, err, p.stderr.read().decode()[:200].strip())
