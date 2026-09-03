[ 🇺🇸 [Read in English](README.md) ] | [ 🇨🇱 Español ]

[![tests](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml/badge.svg)](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml)

# chile-pension-fund-switching-cost

¿Cuánto cuesta realmente cambiarse de fondo de pensiones en pánico durante una caída? Este proyecto lo responde con **datos diarios reales** de la Superintendencia de Pensiones (2002-2026, ~278.000 filas), no con un mercado simulado.

## Los datos reales

La Superintendencia de Pensiones publica el `valor cuota` diario y el `valor patrimonio` (AUM) de cada AFP, para cada uno de los 5 multifondos (A = más renta variable, E = más conservador), desde 2002. No está expuesto como una API limpia — es un endpoint `.php` detrás de un formulario (`spensiones.cl/apps/valoresCuotaFondo/`) que devuelve un archivo de texto separado por punto y coma. `etl/fetch_valor_cuota.py` reproduce esa consulta en Python puro (sin navegador, sin autenticación).

**Una trampa real de calidad de datos que este proyecto tuvo que resolver**: la fila de encabezado (qué AFP está en qué columna) *cambia* cada vez que una AFP entra, sale o se fusiona — 31 veces solo en el archivo del Fondo C, reflejando eventos reales como la consolidación de AFPs bajo Provida, el lanzamiento de AFP Modelo en 2010, y el de AFP Uno en 2019. Una lectura ingenua con un solo encabezado desalinearía silenciosamente las columnas después del primer cambio, mezclando los números de una AFP con los de otra. `etl/parse_valor_cuota.py` reancla las posiciones de columna cada vez que el encabezado se repite — probado en `tests/test_parse_valor_cuota.py` contra un archivo sintético que cambia de encabezado a mitad de camino.

El valor cuota de cada AFP es una serie independiente (se rebasa a CLP 10.000 cada vez que un fondo se lanza), así que los valores crudos no son comparables entre AFPs. `etl/build_duckdb.py` calcula el retorno diario de cada AFP, lo pondera por el patrimonio del día anterior de esa AFP, y compone el retorno ponderado promedio en un solo índice por tipo de fondo — la forma estándar de construir un índice de referencia a partir de series de precios de sus componentes.

## Verificación del índice contra la historia conocida

Antes de confiar en el índice para cualquier análisis, lo verifiqué contra dos caídas que cualquiera en el sistema de pensiones chileno recuerda:

| Evento | Caída Fondo A | Caída Fondo E |
|---|---|---|
| Crisis financiera 2008 (peak a valle nov. 2008) | **-30,8%** | +0,4% |
| Crash COVID (20-feb a 23-mar 2020) | **-24,6%** | -3,7% |

Ambas coinciden con la magnitud públicamente reportada de esas caídas. Que el Fondo A (hasta 80% renta variable) caiga ~25-30% mientras el Fondo E (mayormente renta fija) casi no se mueve es exactamente la diferencia de perfil de riesgo que el sistema de multifondos está diseñado para producir.

![Fondo A vs Fondo E, historia completa](outputs/figures/fund_a_vs_e_history.png)

Escala logarítmica, índice ponderado por patrimonio, base 100 en la fecha más temprana disponible de cada fondo. Los Fondos C y E tienen datos desde 2002-01-02 (el linaje del fondo único pre-reforma); A, B y D parten el 2002-09-28, cuando la reforma de multifondos de 2002 efectivamente dividió el sistema en cinco fondos. Las tres líneas punteadas marcan las ventanas de crisis analizadas abajo — 2008 y 2020 se ven como caídas bruscas y visibles en el Fondo A que el Fondo E apenas registra; 2022 es un desgaste más lento que ambos fondos sienten.

## El contrafactual de cambio en pánico

Para cada crisis, comparo dos trayectorias reales, backtesteadas, usando solo niveles de índice reales en fechas de calendario reales — sin supuestos sintéticos:

- **SE QUEDA**: el dinero se queda en el Fondo A toda la ventana.
- **PÁNICO**: el dinero se mueve de A a E en el valle de la caída (empíricamente, ese momento está más cerca de cuando realmente se dispara el cambio de fondo minorista — después de que la caída ya se sintió, no antes) y vuelve a A recién `N` meses después, cuando la recuperación ya ocurrió sin él.

| Escenario | Se queda en A | Cambio en pánico (A→E→A) | Costo del pánico |
|---|---|---|---|
| GFC 2008, vuelve a los 12 meses | -4,5% | -28,7% | **24,2 pts** |
| COVID 2020, vuelve a los 6 meses | +20,3% | +8,3% | **12,0 pts** |
| COVID 2020, vuelve a los 12 meses | +32,2% | +6,3% | **25,9 pts** |
| Alza de tasas 2022, vuelve a los 12 meses | +5,6% | +5,5% | **0,1 pts** |

![Costo de cambiarse en pánico por escenario](outputs/figures/panic_switch_cost.png)

**Hallazgo honesto, no elegido a dedo**: el escenario 2022 muestra un costo casi nulo. Eso es real — la crisis de 2022 fue un reajuste lento y sostenido impulsado por alzas de tasas e inflación, no una caída brusca en V. Los bonos (lo que el Fondo E tiene mayoritariamente) también se vendieron ese año, así que huir a E no protegió realmente nada, y no hubo una recuperación brusca en A que perderse. La penalización del pánico no es un impuesto universal — es específicamente el costo de errar el timing de una caída-y-recuperación-en-V pronunciada, que es exactamente lo que fueron 2008 y 2020, y lo que 2022 no fue.

## Reproducirlo

```bash
pip install -r requirements.txt
python etl/fetch_valor_cuota.py      # descarga los 5 archivos fuente reales (~7MB)
python etl/parse_valor_cuota.py      # -> data/processed/valor_cuota_long.parquet
python etl/build_duckdb.py           # -> data/pension_funds.duckdb
python analysis/panic_switch_cost.py # -> reports/panic_switch_results.csv
python scripts/make_charts.py        # -> outputs/figures/*.png
pytest tests/ -v                     # 9 tests, sin necesidad de red (fixtures sintéticas)
```

## Próximos pasos

El modelo de cambio en pánico asume un solo movimiento de suma total en el valle — un afiliado real podría cambiarse gradualmente o varias veces (la ley limita los cambios por año, algo que este proyecto no rastrea). Un seguimiento lógico: extraer los boletines mensuales de volumen de traspasos (`Compendio de Pensiones`, publicados en PDF) para verificar si el volumen real de cambios efectivamente se dispara cerca de los valles que este proyecto identificó, cerrando el ciclo entre "cuánto cuesta" y "si la gente realmente lo hace".

## Autor

Pablo Reyes — Data Scientist, Santiago, Chile.

Licencia: MIT — ver [LICENSE](LICENSE).
