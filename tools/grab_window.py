"""Capture a single Windows window to a PNG — the way Discord's window share works.

This exists to close the one real gap in the UEFN tooling: UMG widgets cannot be
screenshotted from inside the editor (PIE can't be started from Python, WidgetComponent
render targets never allocate, a Launch Session is a separate process). But the editor
*window itself* can be captured from outside, so a widget open in the UMG designer is
visible after all.

Only the window you name is captured — not the whole screen, and nothing is captured
without an explicit call.

Usage:
    python grab_window.py --list
    python grab_window.py --title "PrestigeRoadmap" --out shot.png
    python grab_window.py --title "UnrealEditorFortnite" --out shot.png --client-only
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

user32.SetProcessDPIAware()

SRCCOPY = 0x00CC0020
#: Renders windows that draw through DirectX/composition, which plain BitBlt misses.
PW_RENDERFULLCONTENT = 0x00000002
DWMWA_EXTENDED_FRAME_BOUNDS = 9


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def list_windows(min_size=200):
    """Visible top-level windows with a title, as [(hwnd, title, w, h)]."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w >= min_size and h >= min_size:
            found.append((hwnd, buf.value, w, h))
        return True

    user32.EnumWindows(callback, 0)
    return found


def find_window(needle):
    """The largest visible window whose title contains `needle` (case-insensitive).

    Largest wins because an app often has small helper windows sharing its name; the
    one you meant is almost always the big one.
    """
    matches = [w for w in list_windows() if needle.lower() in w[1].lower()]
    if not matches:
        return None
    return max(matches, key=lambda w: w[2] * w[3])


def capture(hwnd, out_path, client_only=False):
    """Capture one window to a PNG. Returns (width, height)."""
    from PIL import Image

    if client_only:
        rect = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        width, height = rect.right, rect.bottom
    else:
        # The DWM frame bounds exclude the invisible resize border that GetWindowRect
        # includes, so the capture isn't padded with transparent edges.
        rect = wt.RECT()
        if dwmapi.DwmGetWindowAttribute(
                wt.HWND(hwnd), wt.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top

    if width <= 0 or height <= 0:
        raise RuntimeError("window has no drawable area (minimised?)")

    hdc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)

    ok = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    if not ok:                      # some windows only respond to a plain blit
        gdi32.BitBlt(mem_dc, 0, 0, width, height, hdc, 0, 0, SRCCOPY)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height        # negative = top-down rows
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)

    image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    image.save(out_path)
    return width, height


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="list capturable windows")
    ap.add_argument("--title", help="substring of the window title to capture")
    ap.add_argument("--out", default="window.png", help="output PNG path")
    ap.add_argument("--client-only", action="store_true",
                    help="drop the title bar and borders")
    args = ap.parse_args()

    if args.list or not args.title:
        for hwnd, title, w, h in sorted(list_windows(), key=lambda x: -(x[2] * x[3])):
            print("%8d  %5dx%-5d  %s" % (hwnd, w, h, title))
        return 0

    match = find_window(args.title)
    if match is None:
        print("no visible window matching %r — try --list" % args.title, file=sys.stderr)
        return 1
    hwnd, title, _, _ = match
    w, h = capture(hwnd, args.out, args.client_only)
    print("captured %dx%d from %r -> %s" % (w, h, title, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
