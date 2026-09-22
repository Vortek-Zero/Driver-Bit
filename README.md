# 🏎️ WheelBridge — volante + pedais + câmbio de micro:bit no PC

![CI](https://github.com/Vortek-Zero/Driver-Bit/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Linux](https://img.shields.io/badge/linux-uinput-green)
![Windows](https://img.shields.io/badge/windows-exe%20portátil-blue)

Transforme **3 micro:bits baratos** num **cockpit completo**: volante analógico,
3 pedais ultrassônicos (embreagem, freio, acelerador — na ordem do carro) e
câmbio sequencial — com o **volante sem fio** via rádio. O PC enxerga tudo como
um **controle de verdade** (gamepad no Linux, teclado no Windows) para jogar
**Slow Roads** e qualquer outro jogo.

```
 volantesem fio ──rádio──┐
 câmbio sem fio ──rádio──┤
                         ▼
              ┌─── HUB (USB, pedais) ─── STEER/GEAR/SHIFT/MODE/HANDBRAKE/BRAKE/ACCEL/CLUTCH
              │                              │
              │                    ┌─────────┴──────────┐
              │                    ▼                    ▼
              │            gamepad Linux (--gamepad)  teclado Windows (--keyboard / .exe)
              │                    │                    │
              └──────── dashboard http://127.0.0.1:8123 (calibração + telemetria ao vivo)
```

## ⚡ Começo rápido

### Windows (escola, sem instalar nada)

1. Baixe **`WheelBridge.exe`** em [Releases](../../releases) + a pasta [`firmware/`](firmware/).
2. Grave cada `.txt` da pasta no seu micro:bit ([como gravar](#-firmwares)).
3. Espete o **hub** no USB, duplo clique no `.exe`, calibre o centro no painel.
4. Abra o Slow Roads e dirija. É só isso — sem Python, sem terminal, sem admin.

### Linux (esta máquina)

```bash
pip install -r requirements.txt        # pyserial (+ evdev p/ --gamepad)
python check.py                        # F5: verifica placas, protocolo e saída
python main.py --port auto --gamepad   # hub + gamepad virtual
# http://127.0.0.1:8123 → calibrar centro → Slow Roads → Settings → Controls → Controller
```

## 🧩 Hardware (3 micro:bits, grupo de rádio 7)

| Placa | Função | Conexão | Firmware |
|---|---|---|---|
| Volante | direção + modo + freio de mão | bateria (sem fio) ou USB | [`firmware/volante.txt`](firmware/volante.txt) |
| Hub/pedais | 3 ultrassons + relay rádio→USB | **USB no PC** (única) | [`firmware/pedais.txt`](firmware/pedais.txt) |
| Câmbio | sobe/desce marcha | bateria (sem fio) | [`firmware/cambio.txt`](firmware/cambio.txt) |

Fiação dos ultrassons (imutável — GND→GND, 3V3→VCC em todos):

| Pedal | SIG | NC | Ordem no carro |
|---|---|---|---|
| Embreagem | **P2** | **P16** | ⬅️ esquerda |
| Freio | **P0** | **P14** | centro |
| Acelerador | **P1** | **P15** | direita ➡️ |

Controles: girar = direção · A do câmbio = +marcha · B do câmbio = −marcha
**(só com embreagem pressionada — regra de carro real, exibida na matriz)** ·
A do volante = MANUAL/AUTO · B do volante = freio de mão.

## 📻 Protocolo serial (hub → PC, 115200 baud, uma linha por evento)

```
STEER:0 … STEER:359        direção (bússola, graus)
GEAR:UP / GEAR:DOWN        legado (firmware antigo)
SHIFT:UP / SHIFT:DOWN      câmbio (só entra embreado + modo MANUAL)
MODE:AUTO / MODE:MANUAL    botão A do volante
HANDBRAKE:ON / OFF         botão B do volante
BRAKE:<mm> ACCEL:<mm> CLUTCH:<mm>   pedais (0 = sem eco/inválido)
```

O núcleo converte: graus → −1.0…+1.0 (com calibração, zona morta, EMA);
mm → 0.0…1.0 (`far_mm`=50 solto, `near_mm`=20 fundo); `<=0` congela 250ms e
solta por segurança.

## 🎮 Saídas

| Saída | Plataforma | Direção | Pedais | Lenha extra |
|---|---|---|---|---|
| `--gamepad` (uinput, perfil Xbox 360) | Linux | eixo X | LT / RT / THROTTLE | câmbio LB/RB, mão botão B |
| `--keyboard` / `.exe` (SendInput, sem driver) | Windows | setas (PWM) | setas (PWM) | câmbio E/Q, mão Espaço |
| Dashboard web | qualquer | marcador ● | 3 barras | modo, travas, telemetria |

## 🛠️ Comandos úteis

```bash
python -m pytest -q          # 100+ testes (CI roda no Linux + Windows)
python check.py              # diagnóstico F5
python main.py --simulate    # dashboard sem hardware
python main.py --keyboard    # Windows com Python
```

## 🗺️ Roadmap

- [x] Volante USB + dashboard
- [x] Calibração por média + trava-a-trava
- [x] Gamepad Linux + teclado Windows
- [x] Pedais + câmbio via rádio, volante sem fio
- [ ] `.exe` assinado / instalador + ícone
- [ ] Force feedback (vibração do pad no volante?)

Feito com micro:bit, Python e rádio. PRs bem-vindos!
