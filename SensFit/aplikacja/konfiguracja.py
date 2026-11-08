"""Program settings, reading the sensitivity from the CS2 files and installing the GSI file.

Data is kept in %APPDATA%\\SensFit, because the .exe (onefile mode) unpacks into a temporary
folder on every start and nothing would survive there.
"""
import glob
import json
import os
import re

from jezyk import t

FOLDER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SensFit")
FOLDER_SESJI = os.path.join(FOLDER, "sesje")
PLIK_USTAWIEN = os.path.join(FOLDER, "ustawienia.json")
NAZWA_GSI = "gamestate_integration_sensfit.cfg"
M_YAW = 0.022  # default CS2 m_yaw: degrees of rotation per mouse count at sensitivity 1.0
KUBELEK_S = 0.004  # mouse movement is summed in 4 ms buckets (recording and analysis)

# CS2 settings read from the game file (m_yaw, m_pitch and the zoom ratio as well).
# "odczytane" lists the values that were really present in the file; the rest are CS2 defaults.
DOMYSLNE_CS2 = {"sensitivity": None, "m_yaw": M_YAW, "m_pitch": M_YAW, "zoom_sensitivity_ratio": 1.0}
cs2 = dict(DOMYSLNE_CS2, odczytane=set())

TRESC_GSI = """"SensFit"
{
	"uri"		"http://127.0.0.1:3000"
	"timeout"	"1.0"
	"buffer"	"0.0"
	"throttle"	"0.1"
	"heartbeat"	"10.0"
	"data"
	{
		"provider"		"1"
		"player_id"		"1"
		"player_state"		"1"
		"player_weapons"	"1"
	}
}
"""


def edpi(sens, dpi):
    return sens * dpi


def m_yaw():
    """m_yaw from CS2 (last reading), or the default 0.022."""
    return cs2["m_yaw"] or M_YAW


def cm_na_360(sens, dpi):
    """How many cm of mouse travel give a 360 degree turn (with m_yaw read from CS2)."""
    return 360 / (m_yaw() * sens * dpi) * 2.54


def folder_steam():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as klucz:
            return winreg.QueryValueEx(klucz, "SteamPath")[0]
    except (ImportError, OSError):
        return r"C:\Program Files (x86)\Steam"


def odczytaj_cs2(tekst=None):
    """Reads the sensitivity, m_yaw, m_pitch and zoom ratio from the newest CS2 settings file and stores them in `cs2`.

    Missing values (CS2 only writes changed ones) keep their defaults. `tekst` is used by tests.
    """
    if tekst is None:
        wzor = os.path.join(folder_steam(), "userdata", "*", "730", "local", "cfg", "cs2_user_convars*.vcfg")
        for plik in sorted(glob.glob(wzor), key=os.path.getmtime, reverse=True):
            try:
                with open(plik, encoding="utf-8", errors="ignore") as f:
                    tekst = f.read()
            except OSError:
                continue
            if '"sensitivity"' in tekst:
                break
            tekst = None
    cs2.update(DOMYSLNE_CS2, odczytane=set())
    for nazwa in DOMYSLNE_CS2:
        trafienie = re.search(r'"%s"\s+"(-?[\d.]+)"' % nazwa, tekst or "")
        if trafienie:
            try:
                cs2[nazwa] = abs(float(trafienie.group(1))) or DOMYSLNE_CS2[nazwa]  # m_pitch can be negative (inverted axis)
                cs2["odczytane"].add(nazwa)
            except ValueError:
                pass
    return cs2


def opis_cs2():
    """One line with m_yaw, m_pitch, zoom ratio and where they come from (report, Settings)."""
    return " · ".join(f"{n} {cs2[n]:g} " + (t("(z CS2)", "(from CS2)") if n in cs2["odczytane"]
                                           else t("(domyślne)", "(default)"))
                      for n in ("m_yaw", "m_pitch", "zoom_sensitivity_ratio"))


def cs2_uruchomione():
    """True or False depending on whether cs2.exe is running; None outside Windows or when it cannot be checked."""
    if os.name != "nt":
        return None
    import subprocess
    try:
        wynik = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cs2.exe", "/NH"], capture_output=True,
                               text=True, timeout=5, creationflags=0x08000000)  # CREATE_NO_WINDOW
    except (OSError, subprocess.SubprocessError):
        return None
    return "cs2.exe" in wynik.stdout.lower()


def plik_gsi(folder_cfg):
    return os.path.join(folder_cfg, NAZWA_GSI) if folder_cfg else None


def odczytaj_sens_z_cs2():
    """Sensitivity from the CS2 files (also refreshes m_yaw, m_pitch and zoom ratio), or None."""
    return odczytaj_cs2()["sensitivity"]


def znajdz_folder_cfg_cs2():
    """Finds the ...\\game\\csgo\\cfg folder in all Steam libraries."""
    steam = folder_steam()
    biblioteki = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        with open(vdf, encoding="utf-8", errors="ignore") as f:
            biblioteki += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"(.+?)"', f.read())]
    znalezione = []
    for biblioteka in biblioteki:
        cfg = os.path.join(biblioteka, "steamapps", "common",
                           "Counter-Strike Global Offensive", "game", "csgo", "cfg")
        if os.path.isdir(cfg):
            # After the game is moved the old folder stays behind; a real installation has appmanifest_730.acf
            if os.path.exists(os.path.join(biblioteka, "steamapps", "appmanifest_730.acf")):
                return cfg
            znalezione.append(cfg)
    return znalezione[0] if znalezione else None


def popraw_folder_cs2(wybrany):
    """The user may have picked the game folder or cfg directly, so cfg is searched for inside."""
    for koncowka in ("", "cfg", os.path.join("csgo", "cfg"), os.path.join("game", "csgo", "cfg")):
        kandydat = os.path.join(wybrany, koncowka)
        if os.path.isdir(kandydat) and os.path.basename(os.path.normpath(kandydat)) == "cfg":
            return kandydat
    return None


def gsi_zainstalowane(folder_cfg):
    return bool(folder_cfg) and os.path.exists(plik_gsi(folder_cfg))


def zainstaluj_gsi(folder_cfg):
    """Writes the GSI file into the CS2 cfg folder. Returns (success, message)."""
    if not folder_cfg:
        return False, t("Nie znaleziono folderu CS2. Wskaż go przyciskiem „Wybierz folder CS2”.",
                        "CS2 folder not found. Choose it with the “Choose CS2 folder” button.")
    try:
        with open(os.path.join(folder_cfg, NAZWA_GSI), "w", encoding="utf-8") as f:
            f.write(TRESC_GSI)
    except OSError as e:
        return False, t(f"Nie udało się zapisać pliku: {e}", f"Could not save the file: {e}")
    return True, t("Plik zainstalowany. Uruchom CS2 ponownie, żeby gra go wczytała.",
                   "File installed. Restart CS2 so the game loads it.")


def zapisz_json(plik, dane, **opcje):
    """Safe write: a .tmp file first, then a replace. An interrupted write does not damage the old file."""
    os.makedirs(os.path.dirname(plik), exist_ok=True)
    tymczasowy = plik + ".tmp"
    with open(tymczasowy, "w", encoding="utf-8") as f:
        json.dump(dane, f, **opcje)
    os.replace(tymczasowy, plik)


def wczytaj_ustawienia():
    """Returns the settings dict: dpi, sens, folder_cfg, plus jezyk and motyw.

    jezyk = None means the first start, and the program then takes the system language.
    """
    ust = {"dpi": None, "sens": None, "folder_cfg": None, "jezyk": None, "motyw": "ciemny"}
    try:
        with open(PLIK_USTAWIEN, encoding="utf-8") as f:
            ust.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not ust["folder_cfg"] or not os.path.isdir(ust["folder_cfg"]):
        ust["folder_cfg"] = znajdz_folder_cfg_cs2()
    return ust


def zapisz_ustawienia(ust):
    zapisz_json(PLIK_USTAWIEN, ust, indent=2)
