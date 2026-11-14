# freebuff-web

Usa la **CLI di freebuff** ([pacchetto npm `freebuff`](https://www.npmjs.com/package/freebuff), l'assistente AI per il coding da terminale) da **browser**: sul PC, dal telefono in rete locale o ovunque tramite **Tailscale**, anche da più dispositivi insieme sulla stessa sessione.

Lanci `freebuff` in una cartella come sempre: invece di aprirsi nella console, si apre una pagina web con il terminale vero della CLI. Nella console compare un **QR code** da scansionare col telefono.

> **Nota:** freebuff-web funziona solo con la **CLI** di freebuff, quella che si usa da terminale. **Non** è integrato con l'applicazione nativa/desktop di freebuff e non la usa: esegue il comando `freebuff` in un terminale (PTY) e lo mostra nel browser. È un progetto indipendente, non ufficiale.
>
> Solo Windows (usa ConPTY tramite `pywinpty`).

## Funzionalità

- Terminale web completo (xterm.js su una PTY reale): l'interfaccia a schermo intero di freebuff, i comandi `/history`, `/new`, ecc. funzionano come in console.
- `freebuff` (o `freebufft`) apre la sessione nella cartella corrente e inoltra tutti gli argomenti (`--continue`, `--continue <id>`, `--trust-agents`, `login`, `doctor`…). `--version` e `--help` restano in console.
- QR code all'avvio: link Tailscale se attivo, altrimenti rete locale.
- Più dispositivi sulla stessa sessione: **comanda l'ultimo che scrive o tocca**; gli altri vedono lo stesso schermo, adattato.
- Barra per il telefono: campo di testo + tasti Esc, Tab, frecce, Invio, Ctrl+C… (gestisce gli spazi e gli "a capo" aggiunti dalle tastiere mobili).
- Le sessioni restano attive se chiudi o ricarichi la pagina; `http://127.0.0.1:7681/` elenca le sessioni aperte.

## Installazione

Requisiti: Windows, Python 3.10+, la CLI di freebuff installata (`npm i -g freebuff`).

```powershell
git clone https://github.com/XSparter/freebuff-web.git
cd freebuff-web
pip install -r requirements.txt
```

Comando `freebufft` (apre freebuff nel terminale web):

```powershell
$d = (Get-Location).Path
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$d", "User")
```

Facoltativo: fare in modo che **anche `freebuff`** si apra sempre nel terminale web (la cartella `shim` va messa *prima* di quella di npm):

```powershell
$s = Join-Path (Get-Location).Path "shim"
[Environment]::SetEnvironmentVariable("Path", "$s;" + [Environment]::GetEnvironmentVariable("Path","User"), "User")
```

Apri un nuovo terminale dopo aver modificato il PATH.

## Uso

```powershell
cd mio-progetto
freebuff                 # oppure freebufft
freebuff --continue      # riprende l'ultima conversazione
```

Il server parte da solo in background alla prima esecuzione (porta 7681) e resta attivo per le sessioni successive.

| Variabile | Effetto |
|---|---|
| `FREEBUFFT_PORT` | porta del server (default `7681`) |
| `FREEBUFFT_CMD` | comando da eseguire al posto di freebuff |
| `FREEBUFFT_DIRECT=1` | esegue il freebuff originale in console, senza terminale web |

Per fermare il server: termina il processo `pythonw.exe` che esegue `freebuffserver.py serve`.

## Sicurezza ⚠️

Il server ascolta su **tutte le interfacce senza autenticazione**: chiunque possa raggiungere il PC sulla porta 7681 (rete locale, Tailscale) può aprire le sessioni e **scrivere comandi sul tuo computer**. Usalo solo su reti fidate. Le richieste provenienti da pagine di altri siti vengono bloccate (controllo `Origin`).

Se il telefono non si collega, potrebbe servire una regola del firewall di Windows (PowerShell come amministratore):

```powershell
New-NetFirewallRule -DisplayName "freebuff-web 7681" -Direction Inbound -Protocol TCP -LocalPort 7681 -Action Allow
```

## Licenza

[MIT](LICENSE)
