"""¿Cuánta *pensión* cuesta el cambio en pánico? No cuántos puntos de rentabilidad.

Todo el análisis previo de este repositorio mide el costo sobre un monto único:
cuánto habría crecido un peso que ya estaba adentro. Esa es la pregunta de un
inversionista, y no es la de un afiliado. Este módulo simula una carrera
previsional completa y mide la pérdida donde importa: en la pensión.

**Tres cosas que una carrera tiene y un monto único no.**

1. **Cotizaciones mensuales.** Durante la caída las cotizaciones compran cuotas
   baratas. Quien se cambia al E deja de comprar barato mientras está afuera.
   Este módulo separa ese *efecto aporte* del *efecto saldo* (el capital ya
   acumulado que se mueve al piso). Spoiler honesto: el efecto aporte resultó
   chico -- doce meses de cotizaciones pesan poco frente a un saldo de décadas.
2. **La edad.** Lo que cambia todo. Una pérdida en el saldo es permanente: una
   vez que las dos trayectorias vuelven al mismo fondo crecen igual, así que la
   recuperación que no se vivió no se recupera nunca. Pero para alguien joven esa
   pérdida se diluye en las décadas de cotizaciones que vienen después; para
   alguien cerca de jubilar no hay con qué diluirla.
3. **Las reglas del sistema.** La Ley 19.795 (multifondos) prohíbe el Fondo A para
   el saldo obligatorio de hombres desde los 56 años y mujeres desde los 51. Una
   simulación que deja a alguien de 60 en el Fondo A describe a un afiliado que
   no puede existir. Acá el afiliado está en el fondo más riesgoso que la ley le
   permite: A hasta los 55, B desde los 56.

**Todo en UF.** El índice nominal lleva la inflación adentro (~3,8% anual en la
muestra) y el sueldo crece en términos reales; mezclar las dos cosas infla el
saldo frente al sueldo. La primera versión de este archivo lo hizo y daba
pérdidas de $494.000 mensuales para un sueldo de $800.000.

**Qué es real y qué no.** El índice es real donde hay datos (2002-2026). Una
carrera dura 40 años, así que fuera de esa ventana se usa el retorno real medio
geométrico de cada fondo, de forma determinista. Antes de 2002 el sistema de
multifondos ni siquiera existía, así que ese tramo es un artificio de modelación,
no "lo que hizo el Fondo A". El resultado principal apenas depende de él, porque
**las dos decisiones comparten ese tramo** y crecen igual en él;
`sensibilidad_al_supuesto_externo()` lo mide en vez de pedir que se crea.

**Simplificaciones declaradas.** Afiliado hombre, cotización continua (sin
lagunas: la densidad real de cotización en Chile es bastante menor, lo que baja
el *nivel* de la pensión pero no el *porcentaje* perdido), y una anualidad cierta
en vez de una renta vitalicia con tablas de mortalidad.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "pension_funds.duckdb"
REPORTS_DIR = ROOT / "reports"

EDAD_INICIO_COTIZACION = 25
EDAD_JUBILACION = 65

# Ley 19.795: hombres desde los 56 años no pueden mantener el saldo obligatorio
# en el Fondo A. (Para mujeres el corte es 51 y la edad legal de jubilación 60.)
EDAD_MAXIMA_FONDO_A = 55

TASA_COTIZACION = 0.10

# Sueldo de referencia: 20 UF (~$820.000 a la UF de octubre 2026). El resultado
# principal es un PORCENTAJE y no depende de este valor: duplicar el sueldo
# duplica el saldo de las dos decisiones por igual.
SALARIO_MENSUAL_UF = 20.0
CRECIMIENTO_SALARIAL_REAL_ANUAL = 0.01

# Conversión de saldo a pensión: anualidad cierta de 20 años al 2% real. NO es
# una renta vitalicia (sin tablas de mortalidad RV-2020/CB-2014, sin
# beneficiarios, sin la tasa de venta vigente). Sirve para expresar la pérdida en
# pensión mensual; no para estimar la pensión de nadie.
ANUALIDAD_ANIOS = 20
ANUALIDAD_TASA_ANUAL = 0.02

FONDO_REFUGIO = "E"


def factor_anualidad(anios: int = ANUALIDAD_ANIOS,
                     tasa_anual: float = ANUALIDAD_TASA_ANUAL) -> float:
    """Valor presente de recibir 1 UF al mes durante `anios`, a `tasa_anual`."""
    r = tasa_anual / 12.0
    n = anios * 12
    if r == 0:
        return float(n)
    return (1 - (1 + r) ** -n) / r


def mes_absoluto(d: date) -> int:
    """Número de mes de calendario. Es la única indexación segura entre fondos.

    La primera versión de este módulo indexaba cada serie por posición desde su
    propio primer mes. El Fondo A empieza en septiembre de 2002 y el E en enero,
    así que el mismo índice entero apuntaba a meses distintos en cada fondo: el
    precio del E quedaba desfasado ocho meses y el resultado era silenciosamente
    falso. `test_pension_loss.py` fija esto con dos series de inicio distinto.
    """
    return d.year * 12 + (d.month - 1)


@dataclass(frozen=True)
class SerieMensual:
    """Índice real de un fondo a fin de cada mes, más su retorno medio."""

    fondo: str
    mes_inicial: int                  # mes_absoluto del primer valor
    valores: tuple[float, ...]
    retorno_mensual_medio: float      # geométrico, sobre toda la muestra

    def indice_en(self, mes_abs: int) -> float:
        """Valor del índice en un mes de calendario.

        Fuera de la muestra se extrapola con el retorno medio geométrico. Es
        determinista a propósito: el punto de la comparación es que las dos
        decisiones viven exactamente el mismo mercado, y un componente
        estocástico solo agregaría ruido a esa igualdad.
        """
        i = mes_abs - self.mes_inicial
        n = len(self.valores)
        if 0 <= i < n:
            return self.valores[i]
        if i < 0:
            return self.valores[0] * (1 + self.retorno_mensual_medio) ** i
        return self.valores[-1] * (1 + self.retorno_mensual_medio) ** (i - n + 1)


def cargar_serie_mensual(con: duckdb.DuckDBPyConnection, fondo: str) -> SerieMensual:
    """Último valor del índice REAL (en UF) de cada mes calendario."""
    filas = con.execute(
        """
        SELECT fecha, index_value FROM (
            SELECT fecha, index_value,
                   ROW_NUMBER() OVER (
                       PARTITION BY date_trunc('month', fecha)
                       ORDER BY fecha DESC
                   ) AS rn
            FROM fund_index_real WHERE fondo = ?
        ) WHERE rn = 1 ORDER BY fecha
        """,
        [fondo],
    ).fetchall()
    valores = tuple(float(v) for _, v in filas)
    meses = len(valores) - 1
    retorno = (valores[-1] / valores[0]) ** (1 / meses) - 1
    return SerieMensual(fondo, mes_absoluto(filas[0][0]), valores, retorno)


def cargar_series(con: duckdb.DuckDBPyConnection) -> dict[str, SerieMensual]:
    return {f: cargar_serie_mensual(con, f) for f in ("A", "B", "E")}


def fondo_de_riesgo(edad: float) -> str:
    """El fondo más riesgoso que la ley permite a esa edad (hombre)."""
    return "A" if edad < EDAD_MAXIMA_FONDO_A + 1 else "B"


def simular_carrera(
    series: dict[str, SerieMensual],
    edad_al_evento: int,
    fecha_evento: date,
    meses_fuera: int,
    aporta_en_fondo_refugio: bool = True,
    salario_inicial: float = SALARIO_MENSUAL_UF,
    fecha_cambio: date | None = None,
) -> float:
    """Saldo en UF al jubilarse de un afiliado que cotiza mes a mes.

    `fecha_evento` ancla la carrera: es el día en que el afiliado tiene
    `edad_al_evento`. `fecha_cambio` es cuándo se cambia, y por omisión coincide.
    Separarlas permite comparar dos reglas de pánico sobre la MISMA persona: si
    la carrera se anclara en la fecha del cambio, cambiarse diez meses antes
    simularía a alguien nacido diez meses antes, y la comparación mezclaría la
    decisión con un cambio de cohorte.

    `meses_fuera = 0` es quedarse. Con `meses_fuera > 0` todo el saldo pasa al
    Fondo E el mes de `fecha_evento` y vuelve al fondo de riesgo ese número de
    meses después.

    `aporta_en_fondo_refugio=False` deja las cotizaciones yendo al fondo de
    riesgo aunque el saldo esté en el E. No es una decisión que alguien tome: es
    el contrafactual que separa el efecto saldo del efecto aporte.
    """
    mes_evento = mes_absoluto(fecha_evento)
    mes_cambio = mes_absoluto(fecha_cambio or fecha_evento)
    mes_inicio = mes_evento - (edad_al_evento - EDAD_INICIO_COTIZACION) * 12
    mes_fin = mes_evento + (EDAD_JUBILACION - edad_al_evento) * 12

    cuotas = {f: 0.0 for f in series}
    salario = salario_inicial

    def mover(desde: str, hacia: str, precio: dict[str, float]) -> None:
        # Un traspaso convierte cuotas de un fondo en cuotas de otro conservando
        # el valor al precio del día, que es como funciona en la práctica.
        if desde != hacia and cuotas[desde]:
            cuotas[hacia] += cuotas[desde] * precio[desde] / precio[hacia]
            cuotas[desde] = 0.0

    for m in range(mes_inicio, mes_fin + 1):
        if m > mes_inicio and (m - mes_inicio) % 12 == 0:
            salario *= 1 + CRECIMIENTO_SALARIAL_REAL_ANUAL

        edad = edad_al_evento + (m - mes_evento) / 12
        objetivo = fondo_de_riesgo(edad)
        precio = {f: s.indice_en(m) for f, s in series.items()}
        en_refugio = meses_fuera > 0 and mes_cambio <= m < mes_cambio + meses_fuera

        if en_refugio and m == mes_cambio:
            for f in list(cuotas):
                mover(f, FONDO_REFUGIO, precio)
        elif not en_refugio:
            # Fuera del refugio todo vive en el fondo de riesgo vigente. Esto
            # también ejecuta el traspaso obligatorio A -> B a los 56, y el
            # regreso desde el E al terminar `meses_fuera`.
            for f in list(cuotas):
                mover(f, objetivo, precio)

        destino = FONDO_REFUGIO if (en_refugio and aporta_en_fondo_refugio) else objetivo
        cuotas[destino] += salario * TASA_COTIZACION / precio[destino]

    return sum(c * series[f].indice_en(mes_fin) for f, c in cuotas.items())


@dataclass(frozen=True)
class ResultadoPension:
    evento: str
    edad_al_evento: int
    fondo_al_evento: str
    anios_hasta_jubilar: int
    saldo_quedarse: float
    saldo_panico: float
    pension_quedarse: float
    pension_panico: float
    efecto_saldo: float
    efecto_aporte: float

    @property
    def perdida(self) -> float:
        return self.saldo_quedarse - self.saldo_panico

    @property
    def perdida_pct(self) -> float:
        """% del saldo final -- y por lo tanto de la pensión -- que se destruye."""
        return self.perdida / self.saldo_quedarse * 100 if self.saldo_quedarse else 0.0

    @property
    def perdida_pension(self) -> float:
        return self.pension_quedarse - self.pension_panico

    @property
    def efecto_aporte_pct(self) -> float:
        return self.efecto_aporte / self.perdida * 100 if self.perdida else 0.0


def evaluar_cohorte(
    series: dict[str, SerieMensual],
    evento: str,
    fecha_evento: date,
    edad_al_evento: int,
    meses_fuera: int,
    fecha_cambio: date | None = None,
) -> ResultadoPension:
    quedarse = simular_carrera(series, edad_al_evento, fecha_evento, 0)
    panico = simular_carrera(series, edad_al_evento, fecha_evento, meses_fuera,
                             fecha_cambio=fecha_cambio)
    solo_saldo = simular_carrera(series, edad_al_evento, fecha_evento, meses_fuera,
                                 aporta_en_fondo_refugio=False, fecha_cambio=fecha_cambio)
    fa = factor_anualidad()
    return ResultadoPension(
        evento=evento,
        edad_al_evento=edad_al_evento,
        fondo_al_evento=fondo_de_riesgo(edad_al_evento),
        anios_hasta_jubilar=EDAD_JUBILACION - edad_al_evento,
        saldo_quedarse=quedarse,
        saldo_panico=panico,
        pension_quedarse=quedarse / fa,
        pension_panico=panico / fa,
        efecto_saldo=quedarse - solo_saldo,
        efecto_aporte=solo_saldo - panico,
    )


def sensibilidad_al_supuesto_externo(
    series: dict[str, SerieMensual],
    fecha_evento: date,
    edad_al_evento: int,
    meses_fuera: int,
) -> list[tuple[float, float]]:
    """Pérdida porcentual con el retorno extrapolado escalado entre ×0,5 y ×1,5.

    Si el resultado dependiera del tramo extrapolado, el módulo sería un
    ejercicio sobre un número inventado. Esto lo pone a prueba.
    """
    salida = []
    for k in (0.5, 0.75, 1.0, 1.25, 1.5):
        escaladas = {f: replace(s, retorno_mensual_medio=s.retorno_mensual_medio * k)
                     for f, s in series.items()}
        r = evaluar_cohorte(escaladas, "", fecha_evento, edad_al_evento, meses_fuera)
        salida.append((k, r.perdida_pct))
    return salida


# Las tres caídas de 15% o más del Fondo A en términos REALES (máximo previo,
# piso). No son las mismas tres del análisis nominal: en UF, 2011 queda adentro
# del hoyo de la GFC -- que tardó hasta 2014 en recuperarse -- y aparece
# 2021-2023, que en pesos corrientes parecía un año malo y en poder adquisitivo
# fue una caída de 25,8%.
EVENTOS = {
    "GFC 2008": (date(2007, 11, 2), date(2008, 11, 21)),
    "COVID 2020": (date(2020, 2, 14), date(2020, 3, 20)),
    "Inflación 2021-23": (date(2021, 11, 19), date(2023, 5, 5)),
}
EDADES = (30, 40, 50, 60)
MESES_FUERA = 12

# Dos reglas de pánico, por la razón que documenta `bootstrap_cost.py`: el piso
# es retrospectivo -- nadie sabe que está en él -- y elegirlo garantiza que lo
# que sigue es una subida. Es el peor caso, no el caso típico. La regla
# observable se cambia el día en que la pérdida desde el máximo cruza el umbral,
# que es algo que una persona sí ve en su cartola.
UMBRAL_OBSERVABLE = 0.15


def fecha_regla_observable(con: duckdb.DuckDBPyConnection, maximo: date,
                           umbral: float = UMBRAL_OBSERVABLE) -> date:
    """Primer día en que el Fondo A real cae `umbral` desde su máximo corrido.

    Con la resolución mensual de `simular_carrera`, el traspaso se ejecuta al
    cierre del mes de esa fecha: unos días o semanas después de verla, que es
    del orden de lo que tarda un traspaso real.
    """
    fila = con.execute(
        """
        SELECT fecha FROM (
            SELECT fecha, index_value,
                   max(index_value) OVER (ORDER BY fecha) AS maximo_corrido
            FROM fund_index_real WHERE fondo = 'A' AND fecha >= ?
        ) WHERE index_value / maximo_corrido - 1 <= ? ORDER BY fecha LIMIT 1
        """,
        [maximo, -umbral],
    ).fetchone()
    if fila is None:
        raise ValueError(f"el Fondo A no cae {umbral:.0%} después de {maximo}")
    return fila[0]


def uf_vigente(con: duckdb.DuckDBPyConnection) -> tuple[date, float]:
    return con.execute(
        "SELECT fecha, uf FROM uf_daily ORDER BY fecha DESC LIMIT 1").fetchone()


def main() -> None:
    import csv

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)
    series = cargar_series(con)
    fecha_uf, uf_hoy = uf_vigente(con)
    fechas_regla = {nombre: {"piso": piso,
                             "observable": fecha_regla_observable(con, maximo)}
                    for nombre, (maximo, piso) in EVENTOS.items()}
    con.close()

    print("Pérdida previsional del cambio en pánico, por edad (UF, términos reales)")
    print(f"  hombre, {SALARIO_MENSUAL_UF:.0f} UF/mes, cotiza {TASA_COTIZACION:.0%} de los "
          f"{EDAD_INICIO_COTIZACION} a los {EDAD_JUBILACION}; fondo A hasta los "
          f"{EDAD_MAXIMA_FONDO_A}, B después; vuelve {MESES_FUERA} meses después")
    print("  retorno real medio fuera de 2002-2026: " + ", ".join(
        f"{f} {((1 + s.retorno_mensual_medio) ** 12 - 1):+.2%}" for f, s in series.items()))
    print(f"  pesos de hoy a UF {uf_hoy:,.2f} ({fecha_uf})")
    print("  piso = peor caso, con retrospectiva | observable = al cruzar -15% desde el máximo")
    print()

    resultados: list[tuple[str, ResultadoPension]] = []
    for nombre in EVENTOS:
        f_piso = fechas_regla[nombre]["piso"]
        f_obs = fechas_regla[nombre]["observable"]
        print(f"  {nombre}   piso {f_piso}   observable {f_obs}")
        print(f"  {'edad':>5} {'fondo':>6} {'pensión quedarse':>17}"
              f" {'piso: % pensión':>16} {'observable: % pensión':>22} {'piso: por aportes':>18}")
        for edad in EDADES:
            # La misma persona -- `edad` años el día del piso -- en las dos reglas.
            r_piso = evaluar_cohorte(series, nombre, f_piso, edad, MESES_FUERA)
            r_obs = evaluar_cohorte(series, nombre, f_piso, edad, MESES_FUERA,
                                    fecha_cambio=f_obs)
            resultados += [("piso", r_piso), ("observable", r_obs)]
            print(f"  {edad:>5} {r_piso.fondo_al_evento:>6}"
                  f" {r_piso.pension_quedarse:>13.2f} UF"
                  f" {-r_piso.perdida_pct:>+15.1f}%"
                  f" {-r_obs.perdida_pct:>+21.1f}%"
                  f" {r_piso.efecto_aporte_pct:>17.0f}%")
        print()

    out = REPORTS_DIR / "pension_loss.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["evento", "regla", "fecha_cambio", "edad_al_evento", "fondo_al_evento",
                    "anios_hasta_jubilar", "saldo_quedarse_uf", "saldo_panico_uf",
                    "perdida_pct", "pension_quedarse_uf", "pension_panico_uf",
                    "perdida_pension_uf", "efecto_saldo_uf", "efecto_aporte_uf"])
        for regla, r in resultados:
            w.writerow([r.evento, regla, fechas_regla[r.evento][regla], r.edad_al_evento,
                        r.fondo_al_evento, r.anios_hasta_jubilar,
                        round(r.saldo_quedarse, 2), round(r.saldo_panico, 2),
                        round(r.perdida_pct, 3), round(r.pension_quedarse, 3),
                        round(r.pension_panico, 3), round(r.perdida_pension, 3),
                        round(r.efecto_saldo, 2), round(r.efecto_aporte, 2)])

    print("  Signo: negativo = la pensión baja por haberse cambiado; positivo = sube.")
    print("  '% pensión' no depende del sueldo. Cotización continua y anualidad cierta")
    print("  de 20 años al 2% real: los porcentajes son el resultado, no los pesos.")
    print()
    print("  Sensibilidad al tramo extrapolado (COVID 2020, piso, 40 años):")
    for k, pct in sensibilidad_al_supuesto_externo(series, fechas_regla["COVID 2020"]["piso"],
                                                   40, MESES_FUERA):
        print(f"    retorno medio × {k:.2f} -> pérdida {pct:.2f}% de la pensión")
    print()
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
