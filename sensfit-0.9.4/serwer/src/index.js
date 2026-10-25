const DISCORD = "https://discord.com/api/v10";
const ODNOWIENIE_MAX_DNI = 60; // bilet starszy niż tyle dni wymaga ponownego logowania

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (req.method === "GET" && url.pathname === "/login") return login(url, env);
      if (req.method === "POST" && url.pathname === "/bilet") return await nowyBilet(req, env);
      if (req.method === "POST" && url.pathname === "/odnow") return await odnow(req, env);
      if (url.pathname === "/") return new Response("SensFit – serwer dostępu działa.");
      return odp(404, { blad: "nie_ma" });
    } catch (e) {
      if (e instanceof Odmowa) return odp(e.status, { blad: e.kod, komunikat: e.message });
      console.log("blad", e && e.stack);
      return odp(500, { blad: "serwer", komunikat: "Błąd serwera. Spróbuj za chwilę." });
    }
  },
};

class Odmowa extends Error {
  constructor(status, kod, komunikat) {
    super(komunikat);
    this.status = status;
    this.kod = kod;
  }
}

function odp(status, dane) {
  return new Response(JSON.stringify(dane), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// ---------------------------------------------------------------- logowanie

function adresZwrotny(port) {
  const p = Number(port);
  if (!Number.isInteger(p) || p < 1024 || p > 65535) throw new Odmowa(400, "port", "Zły port.");
  return `http://127.0.0.1:${p}/callback`;
}

function login(url, env) {
  const redirect = adresZwrotny(url.searchParams.get("port"));
  const state = (url.searchParams.get("state") || "").slice(0, 100);
  const cel = new URL("https://discord.com/oauth2/authorize");
  cel.searchParams.set("client_id", env.DISCORD_CLIENT_ID);
  cel.searchParams.set("response_type", "code");
  cel.searchParams.set("redirect_uri", redirect);
  cel.searchParams.set("scope", "identify guilds.members.read");
  cel.searchParams.set("state", state);
  cel.searchParams.set("prompt", "none"); // przy kolejnym logowaniu bez ponownej zgody
  return Response.redirect(cel.toString(), 302);
}

async function nowyBilet(req, env) {
  const { code, redirect_uri, hw } = await req.json();
  sprawdzHw(hw);
  if (!code || typeof code !== "string") throw new Odmowa(400, "kod", "Brak kodu logowania.");
  let port = null;
  try {
    port = new URL(redirect_uri).port;
  } catch {}
  if (!port || redirect_uri !== adresZwrotny(port)) throw new Odmowa(400, "redirect", "Zły adres zwrotny.");

  const tokeny = await tokenDiscord(env, { grant_type: "authorization_code", code, redirect_uri });
  const czlonek = await sprawdzRole(tokeny.access_token, env);
  const id = czlonek.user.id;

  const konto = (await env.KONTA.get(`u:${id}`, "json")) || { hw: [] };
  dodajKomputer(konto, hw, env);
  zapiszTokeny(konto, tokeny);
  konto.nazwa = czlonek.user.global_name || czlonek.user.username;
  await env.KONTA.put(`u:${id}`, JSON.stringify(konto));
  console.log("login", id, konto.nazwa);
  return odp(200, { bilet: await wystawBilet(env, id, konto.nazwa, hw) });
}

async function odnow(req, env) {
  const { bilet, hw } = await req.json();
  sprawdzHw(hw);
  const dane = await odczytajBilet(env, bilet);
  if (!dane || dane.hw !== hw) throw new Odmowa(401, "bilet", "Zaloguj się ponownie.");
  if (Date.now() / 1000 - dane.iat > ODNOWIENIE_MAX_DNI * 86400)
    throw new Odmowa(401, "bilet", "Zaloguj się ponownie.");

  const konto = await env.KONTA.get(`u:${dane.uid}`, "json");
  if (!konto || !konto.hw.includes(hw)) throw new Odmowa(401, "bilet", "Zaloguj się ponownie.");

  let token = konto.at;
  if (!token || konto.at_do < Date.now() + 3600e3) {
    let nowe;
    try {
      nowe = await tokenDiscord(env, { grant_type: "refresh_token", refresh_token: konto.rt });
    } catch (e) {
      if (e instanceof Odmowa && e.kod === "discord_token") throw new Odmowa(401, "bilet", "Zaloguj się ponownie.");
      throw e;
    }
    zapiszTokeny(konto, nowe);
    await env.KONTA.put(`u:${dane.uid}`, JSON.stringify(konto));
    token = nowe.access_token;
  }
  const czlonek = await sprawdzRole(token, env);
  return odp(200, { bilet: await wystawBilet(env, dane.uid, czlonek.user.global_name || czlonek.user.username, hw) });
}

// ---------------------------------------------------------------- Discord

async function tokenDiscord(env, pola) {
  const r = await fetch(`${DISCORD}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.DISCORD_CLIENT_ID,
      client_secret: env.DISCORD_CLIENT_SECRET,
      ...pola,
    }),
  });
  if (r.status >= 500) throw new Error(`Discord token ${r.status}`);
  if (!r.ok) throw new Odmowa(401, "discord_token", "Logowanie Discord nie powiodło się. Spróbuj jeszcze raz.");
  return r.json();
}

async function sprawdzRole(accessToken, env) {
  const r = await fetch(`${DISCORD}/users/@me/guilds/${env.GUILD_ID}/member`, {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  if (r.status === 404) throw new Odmowa(403, "brak_serwera", "Nie jesteś na serwerze Discord SensFit.");
  if (r.status === 401) throw new Odmowa(401, "bilet", "Zaloguj się ponownie.");
  if (!r.ok) throw new Error(`Discord member ${r.status}`);
  const czlonek = await r.json();
  if (!czlonek.roles.includes(env.ROLE_ID))
    throw new Odmowa(403, "brak_roli", "Nie masz roli testera na serwerze Discord SensFit.");
  return czlonek;
}

function zapiszTokeny(konto, t) {
  konto.at = t.access_token;
  konto.at_do = Date.now() + t.expires_in * 1000;
  konto.rt = t.refresh_token;
}

function sprawdzHw(hw) {
  if (typeof hw !== "string" || !/^[0-9a-f]{32}$/.test(hw)) throw new Odmowa(400, "hw", "Zły kod komputera.");
}

function dodajKomputer(konto, hw, env) {
  if (konto.hw.includes(hw)) return;
  const max = Number(env.MAX_KOMPUTEROW || 2);
  if (konto.hw.length >= max)
    throw new Odmowa(409, "limit_komputerow",
      `To konto Discord jest już używane na ${max} komputerach. Napisz do autora SensFit, żeby zwolnił miejsce.`);
  konto.hw.push(hw);
}

// ---------------------------------------------------------------- bilet (Ed25519)
// Bilet = base64url(JSON) + "." + base64url(podpis). Aplikacja ma wbudowany klucz publiczny.

let kluczCache = null;
async function kluczPrywatny(env) {
  if (!kluczCache) {
    kluczCache = await crypto.subtle.importKey("jwk", JSON.parse(env.KLUCZ_PRYWATNY), { name: "Ed25519" }, true, ["sign"]);
  }
  return kluczCache;
}

async function kluczPublicznyZPrywatnego(env) {
  const jwk = JSON.parse(env.KLUCZ_PRYWATNY);
  return crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: jwk.x }, { name: "Ed25519" }, true, ["verify"]);
}

async function wystawBilet(env, uid, nazwa, hw) {
  const teraz = Math.floor(Date.now() / 1000);
  const dane = { v: 1, uid, nazwa, hw, iat: teraz, exp: teraz + Number(env.WAZNOSC_GODZ || 72) * 3600 };
  const tresc = b64url(new TextEncoder().encode(JSON.stringify(dane)));
  const podpis = await crypto.subtle.sign({ name: "Ed25519" }, await kluczPrywatny(env), new TextEncoder().encode(tresc));
  return `${tresc}.${b64url(new Uint8Array(podpis))}`;
}

// Odczyt biletu do odnowienia: podpis musi być nasz, data ważności może już minąć.
async function odczytajBilet(env, bilet) {
  if (typeof bilet !== "string" || bilet.length > 2000) return null;
  const [tresc, podpis] = bilet.split(".");
  if (!tresc || !podpis) return null;
  const ok = await crypto.subtle.verify({ name: "Ed25519" }, await kluczPublicznyZPrywatnego(env),
    zB64url(podpis), new TextEncoder().encode(tresc));
  if (!ok) return null;
  try {
    return JSON.parse(new TextDecoder().decode(zB64url(tresc)));
  } catch {
    return null;
  }
}

function b64url(bajty) {
  let s = "";
  for (const b of bajty) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function zB64url(s) {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}
