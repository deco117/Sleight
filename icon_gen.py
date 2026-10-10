"""Generate the app icon: expression ribbons rising from piano keys.
Outputs icon.png (1024), icon_256.png, and icon.ico."""
import math

from PIL import Image, ImageDraw, ImageFilter

SS = 4
S = 512 * SS


def bez(p0, p1, p2, n=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1])
            for t in (i / (n - 1) for i in range(n))]


def ribbon(draw, x0, y0, dx, height, col, layer, base_w=0.05):
    top = (x0 + dx, y0 - S * height)
    ctrl = (x0 + dx * 0.5, y0 - S * height * 0.5)
    cl = bez((x0, y0), ctrl, top)
    pts_l, pts_r = [], []
    for i, (x, y) in enumerate(cl):
        t = i / (len(cl) - 1)
        w = (S * base_w * (1 - 0.78 * t)) * layer
        pts_l.append((x - w, y))
        pts_r.append((x + w, y))
    draw.polygon(pts_l + pts_r[::-1], fill=col)
    r = S * 0.026 * layer
    draw.ellipse([top[0] - r, top[1] - r, top[0] + r, top[1] + r], fill=col)


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded-square background with a vertical gradient
    bg = Image.new("RGB", (S, S))
    bd = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / S
        bd.line([(0, y), (S, y)],
                fill=(int(10 + 12 * t), int(12 + 12 * t), int(22 + 22 * t)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S, S], radius=int(S * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)

    # keys - a clean 5-white-key strip with 3 black keys
    kb_top, kb_bot = int(S * 0.72), int(S * 0.90)
    left, right = S * 0.16, S * 0.84
    nw = 5
    wkw = (right - left) / nw
    for i in range(nw):
        x = left + i * wkw
        d.rounded_rectangle([x + wkw * 0.06, kb_top, x + wkw * 0.94, kb_bot],
                            radius=int(S * 0.012), fill=(232, 231, 238))
    for i in (0, 1, 3):     # black keys after white 0,1,3
        x = left + (i + 1) * wkw
        d.rounded_rectangle([x - wkw * 0.30, kb_top, x + wkw * 0.30, kb_top + (kb_bot - kb_top) * 0.60],
                            radius=int(S * 0.008), fill=(16, 16, 22))

    # three ribbons - a chord, each note bending its own way
    specs = [
        (left + 1.5 * wkw, -S * 0.10, 0.46, (120, 225, 255)),   # cyan, bends left
        (left + 2.5 * wkw, S * 0.02, 0.56, (245, 240, 220)),    # near-white, near-straight, tallest
        (left + 3.5 * wkw, S * 0.12, 0.44, (255, 120, 205)),    # rose, bends right
    ]
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for layer, a in ((3.2, 55), (1.7, 120)):
        for x0, dx, h, c in specs:
            ribbon(gd, x0, kb_top, dx, h, c + (a,), layer)
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.018))
    img.alpha_composite(glow)

    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    for x0, dx, h, c in specs:
        ribbon(cd, x0, kb_top, dx, h, c + (255,), 1.0)
    core = core.filter(ImageFilter.GaussianBlur(S * 0.0025))
    img.alpha_composite(core)

    img = img.resize((512, 512), Image.LANCZOS)
    img.save("icon.png")
    img.resize((256, 256), Image.LANCZOS).save("icon_256.png")
    img.save("icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote icon.png, icon_256.png, icon.ico")


if __name__ == "__main__":
    build()
