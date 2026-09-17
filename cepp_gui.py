"""
cepp_gui.py - entry point mong, giu tuong thich nguoc.

Logic thuc te nam trong package cepp_proxy_gui/ (xem README.md phan
"Cau truc du an"). Giu file nay o thu muc goc de:
  - `python cepp_gui.py` van chay duoc nhu truoc.
  - Lenh build PyInstaller hien co (--name cepp_proxy_gui cepp_gui.py)
    khong can doi.

Cach chay tuong duong khac:  python -m cepp_proxy_gui
"""

from cepp_proxy_gui.__main__ import main

if __name__ == "__main__":
    main()
