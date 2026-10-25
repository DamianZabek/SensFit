import glob
import json
import os
import re

FOLDER = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SensFit")
FOLDER_SESJI = os.path.join(FOLDER, "sesje")
PLIK_USTAWIEN = os.path.join(FOLDER, "ustawienia.json")
NAZWA_GSI = "gamestate_integration_sensfit.cfg"
M_YAW = 0.022  # stała CS2: ile stopni obrotu daje 1 count przy sens 1.0

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


def cm_na_360(sens, dpi):
    """Ile cm musisz przesunąć myszkę, żeby obrócić się o 360°."""
    return 360 / (M_YAW * sens * dpi) * 2.54


def folder_steam():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as klucz:
            return winreg.QueryValueEx(klucz, "SteamPath")[0]
    except (ImportError, OSError):
        return r"C:\Program Files (x86)\Steam"


def odczytaj_sens_z_cs2():
    """Szuka 'sensitivity' w plikach ustawień CS2 (bierze najnowszy plik)."""
    wzor = os.path.join(folder_steam(), "userdata", "*", "730", "local", "cfg", "cs2_user_convars*.vcfg")
    for plik in sorted(glob.glob(wzor), key=os.path.getmtime, reverse=True):
        try:
            with open(plik, encoding="utf-8", errors="ignore") as f:
                trafienie = re.search(r'"sensitivity"\s+"([\d.]+)"', f.read())
        except OSError:
            continue
        if trafienie:
            return float(trafienie.group(1))
    return None


def znajdz_folder_cfg_cs2():
    """Znajduje folder ...\\game\\csgo\\cfg we wszystkich bibliotekach Steam."""
    steam = folder_steam()
    biblioteki = [steam]
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        with open(vdf, encoding="utf-8", errors="ignore") as f:
            biblioteki += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"(.+?)"', f.read())]
    for biblioteka in biblioteki:
        cfg = os.path.join(biblioteka, "steamapps", "common",
                           "Counter-Strike Global Offensive", "game", "csgo", "cfg")
        if os.path.isdir(cfg):
            return cfg
    return None


def popraw_folder_cs2(wybrany):
    """Użytkownik mógł wskazać folder gry albo od razu cfg - szukamy cfg w środku."""
    for koncowka in ("", "cfg", os.path.join("csgo", "cfg"), os.path.join("game", "csgo", "cfg")):
        kandydat = os.path.join(wybrany, koncowka)
        if os.path.isdir(kandydat) and os.path.basename(os.path.normpath(kandydat)) == "cfg":
            return kandydat
    return None


def gsi_zainstalowane(folder_cfg):
    return bool(folder_cfg) and os.path.exists(os.path.join(folder_cfg, NAZWA_GSI))


def zainstaluj_gsi(folder_cfg):
    """Zapisuje plik GSI w folderze cfg CS2. Zwraca (sukces, komunikat)."""
    if not folder_cfg:
        return False, "Nie znaleziono folderu CS2. Wskaż go przyciskiem „Wybierz folder CS2”."
    try:
        with open(os.path.join(folder_cfg, NAZWA_GSI), "w", encoding="utf-8") as f:
            f.write(TRESC_GSI)
    except OSError as e:
        return False, f"Nie udało się zapisać pliku: {e}"
    return True, "Plik zainstalowany. Uruchom CS2 ponownie, żeby gra go wczytała."


def wczytaj_ustawienia():
    """Zwraca słownik ustawień: dpi (lub None), sens (lub None), folder_cfg."""
    ust = {"dpi": None, "sens": None, "folder_cfg": None}
    try:
        with open(PLIK_USTAWIEN, encoding="utf-8") as f:
            ust.update(json.load(f))
    except (OSError, ValueError):
        pass
    if not ust["folder_cfg"] or not os.path.isdir(ust["folder_cfg"]):
        ust["folder_cfg"] = znajdz_folder_cfg_cs2()
    return ust


def zapisz_ustawienia(ust):
    os.makedirs(FOLDER, exist_ok=True)
    with open(PLIK_USTAWIEN, "w", encoding="utf-8") as f:
        json.dump(ust, f, indent=2)
