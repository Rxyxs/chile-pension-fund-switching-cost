[ 🇺🇸 [Read in English](README.md) ] | [ 🇨🇱 Español ]

[![tests](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml/badge.svg)](https://github.com/Rxyxs/chile-pension-fund-switching-cost/actions/workflows/tests.yml)

# chile-pension-fund-switching-cost

¿Cuánto cuesta realmente cambiarse de fondo de pensiones en pánico durante una caída? Este proyecto lo responde con **datos diarios reales** de la Superintendencia de Pensiones (2002-2026, ~278.000 filas), no con un mercado simulado.

**Si no conoces bien el sistema de multifondos**: el ahorro previsional obligatorio de cada trabajador está en uno de 5 "multifondos" (A a E) administrados por una AFP. El Fondo A invierte hasta 80% en acciones — mayor retorno esperado, más vaivenes. El Fondo E invierte casi todo en renta fija — menor retorno esperado, vaivenes mucho más chicos. Los afiliados pueden cambiarse de fondo cuando quieran, y el movimiento típico en una caída es huir de A (o B/C) hacia el "más seguro" E — este proyecto mide si ese instinto realmente compensa.

## Lo que encontré

| | |
|---|---|
| **Cambiarse en el piso cuesta caro, casi siempre** | En 2.000 historias sintéticas de 24 años, cambiarse al E en el mínimo de la caída costó en el 97% de los casos (mediana +17,8 puntos en el año siguiente). Para un afiliado de 50 años, eso es entre 13,3% y 18,5% de la pensión, y es permanente. |
| **Pero el piso solo se conoce después** | Nadie sabe que está en el piso. Con una regla que alguien sí podría seguir —cambiarse al cruzar −15% de pérdida— el costo baja a una mediana de +3,4 puntos y ocurre en el 59% de los casos: una moneda al aire con un leve sesgo en contra. El "15 de 15 favorecen quedarse" de la primera versión de este análisis era, en buena parte, ese sesgo de retrospectiva. |
| **No hay una regla que gane de forma confiable** | Los retornos mensuales no son predecibles (AR(1), p = 0,53). La volatilidad sí lo es, pero detecta tormentas, no su dirección. Salir cuando un modelo de régimen detecta turbulencia "ganaba" entre 1,4% y 2,3% al año… hasta quitarle la información del futuro: fuera de muestra y con el rezago real de un traspaso, rinde 0,2% al año menos que quedarse. |
| **En poder adquisitivo, la historia es otra** | Deflactado por la UF, la crisis de 2008 dejó al Fondo A bajo el agua hasta 2014, no hasta 2010. Y 2021–23, que en pesos fue una caída de 14,6% que "no califica", fue en UF una pérdida de 26%: la segunda peor de los 24 años. |
| **El refugio también cae** | El Fondo E protegió en 10 de las 12 tormentas en que cayó el A. Pero tiene su propio riesgo, el de tasas e inflación: perdió 13,1% real en 2021 y lleva −10,5% real en 2026. |

El resto del documento muestra cómo se llegó a cada fila, incluidos los errores que cometí en el camino y cómo quedaron fijados con tests.

## Los datos reales — y qué significa "ponderado por patrimonio"

La Superintendencia de Pensiones publica dos números cada día hábil, para cada AFP, para cada uno de los 5 tipos de fondo:

- **`valor cuota`** (precio de la unidad): piensa en cada fondo como dividido en millones de "cuotas" pequeñas. Este es el precio de una cuota ese día. Por sí solo solo te dice el *retorno* del fondo de esa AFP — no puedes comparar el número crudo entre dos AFPs, porque cada una parte su propio precio de cuota en CLP 10.000 cuando el fondo se crea.
- **`valor patrimonio`** (activos totales administrados): cuánta plata, en total, tiene el fondo de esa AFP ese día.

Este dato no está expuesto como una API limpia — es un endpoint `.php` detrás de un formulario en `spensiones.cl/apps/valoresCuotaFondo/` que devuelve un archivo de texto separado por punto y coma. `etl/fetch_valor_cuota.py` reproduce esa consulta en Python puro (sin navegador, sin login — cualquiera puede correrlo).

**Una trampa real de calidad de datos que este proyecto tuvo que resolver**: la fila de encabezado (qué AFP está en qué columna) *cambia* cada vez que una AFP entra, sale o se fusiona con otra — 31 veces solo en el archivo del Fondo C, reflejando eventos reales como la consolidación de las AFPs bajo Provida, el lanzamiento de AFP Modelo en 2010, y el de AFP Uno en 2019. Si lees este archivo con un solo encabezado fijo (la primera aproximación obvia), todo después del primer cambio se desplaza silenciosamente — terminarías atribuyéndole los números de una AFP al nombre de otra, sin darte cuenta. `etl/parse_valor_cuota.py` relee el encabezado cada vez que se repite y reancla desde ahí qué columna pertenece a qué AFP — exactamente este escenario es lo que `tests/test_parse_valor_cuota.py` verifica con un archivo sintético pequeño construido para cambiar de encabezado a mitad de camino.

**¿Por qué "ponderado por patrimonio"?** Como el `valor cuota` de cada AFP es una serie independiente, no puedes simplemente promediar los precios crudos entre AFPs para obtener "el retorno del Fondo A" — promediar precios de series que partieron en distintos momentos y crecieron por separado da un número sin sentido. Lo que sí puedes hacer es: calcular el retorno porcentual diario propio de cada AFP, y luego promediar esos retornos entre AFPs, ponderando cada uno por cuánta plata (`valor patrimonio`) manejaba realmente el día anterior. Esa ponderación importa — imagina que la AFP X (que administra CLP 9 mil millones) tiene un retorno de -10% un día, y la AFP Y, chica (CLP 1 mil millones), tiene +10% ese mismo día; un promedio simple de los dos retornos diría "0%", pero eso no es lo que realmente le pasó a la plata del sistema — el 90% de los pesos en el sistema perdió 10% ese día. `etl/build_duckdb.py` hace esta ponderación, y luego compone los retornos diarios resultantes en un índice por tipo de fondo (partiendo en 100), que es la forma estándar en que los proveedores de índices (como los detrás del IPSA o el S&P 500) construyen un benchmark a partir de muchos componentes.

## Verificación del índice contra la historia conocida

Antes de confiar en un número que yo mismo calculé, lo verifiqué contra dos caídas que cualquiera en el sistema de pensiones chileno recuerda haber vivido:

| Evento | Caída Fondo A | Caída Fondo E |
|---|---|---|
| Crisis financiera 2008 (peak a valle nov. 2008) | **-30,8%** | +0,4% |
| Crash COVID (20-feb a 23-mar 2020) | **-24,6%** | -3,7% |

("Caída" o *drawdown* acá solo significa: cuánto bajó el índice desde su punto más alto hasta su punto más bajo durante esa crisis, en porcentaje.) Ambos números coinciden con la magnitud de esas caídas tal como se reportó públicamente en su momento. Que el Fondo A (hasta 80% acciones) haya caído ~25-30% mientras el Fondo E (mayormente renta fija) casi no se movió no es coincidencia — es exactamente la diferencia de perfil de riesgo que el sistema de multifondos fue diseñado para producir, y ver que los datos la reproducen de forma independiente es lo que me dice que la lógica de construcción del índice de arriba está efectivamente correcta, no solo que se ve razonable.

![Fondo A vs Fondo E, historia completa](outputs/figures/fondo_a_vs_e_historia.png)

Escala logarítmica, índice ponderado por patrimonio, base 100 en la fecha más temprana disponible de cada fondo. Los Fondos C y E tienen datos desde 2002-01-02 (el linaje del fondo único pre-reforma); A, B y D parten el 2002-09-28, cuando la reforma de multifondos de 2002 efectivamente dividió el sistema en cinco fondos. Las tres líneas punteadas marcan las ventanas de crisis analizadas abajo — 2008 y 2020 se ven como caídas bruscas y visibles en el Fondo A que el Fondo E apenas registra; 2022 es un desgaste más lento que ambos fondos sienten.

**Versión interactiva**: los `outputs/figures/*.png` de arriba son estáticos; correr `python scripts/make_interactive_dashboard.py` genera `outputs/interactive/pension_switching_dashboard.html` — ábrelo en cualquier navegador para hacer zoom a una caída específica, pasar el mouse sobre cualquier día y ver su valor exacto de índice, y pasar el mouse sobre cada barra de costo de pánico abajo para ver los números de "se queda" vs. "pánico" detrás. No está commiteado (está en `.gitignore`) porque el JSON con ~9.000 días × 2 fondos hace el archivo grande; regenerarlo localmente toma segundos una vez que corriste el pipeline de abajo.

## El contrafactual de cambio en pánico

Un "contrafactual" acá solo significa: tomo dos decisiones distintas que un afiliado pudo haber tomado en los *mismos* días reales, usando los *mismos* valores reales del índice, y comparo dónde termina cada una. Nada del mercado está simulado o supuesto — solo las dos decisiones son hipotéticas.

- **SE QUEDA**: el dinero se queda en el Fondo A toda la ventana — la base de "no hacer nada".
- **PÁNICO**: el dinero se mueve de A a E en el valle de la caída (el punto más bajo) — no en la primera señal de problema, porque no es ahí cuando la gente realmente reacciona. El cambio real se dispara *después* de que la caída ya se sintió y dolió, cuando la cartola muestra la pérdida, lo que está más cerca del valle que del peak. El dinero vuelve a A recién `N` meses después, cuando la recuperación ya ocurrió en gran parte sin él.

| Escenario | Se queda en A | Cambio en pánico (A→E→A) | Costo del pánico |
|---|---|---|---|
| GFC 2008, vuelve a los 12 meses | -4,5% | -28,7% | **24,2 pts** |
| COVID 2020, vuelve a los 6 meses | +20,3% | +8,3% | **12,0 pts** |
| COVID 2020, vuelve a los 12 meses | +32,2% | +6,3% | **25,9 pts** |
| Alza de tasas 2022, vuelve a los 12 meses | +5,6% | +5,5% | **0,1 pts** |

(El "costo del pánico", en puntos, es simplemente el porcentaje de SE QUEDA menos el de PÁNICO — p. ej. en la primera fila, quedarse perdió 4,5%, pero el pánico perdió 28,7%, una brecha de **24,2 puntos porcentuales** entre las dos decisiones en los mismos 2 años.)

![Por qué moverse en el piso cuesta](outputs/figures/mecanismo_covid.png)

El mecanismo, sobre la caída de 2020. El Fondo A cae 23% y el Fondo E casi no se mueve —
que es justamente por qué huir se siente correcto en ese momento. El costo no se paga el
día del cambio: se paga en el año siguiente, cuando el Fondo A vuelve a +15% y el Fondo E
termina más o menos donde empezó. Se materializa la caída y después uno se pierde la
recuperación.

![Distribución de los 15 escenarios sistemáticos](outputs/figures/distribucion_escenarios.png)

**Hallazgo honesto, no elegido a dedo**: el escenario 2022 muestra un costo casi nulo, y quiero ser directo en que esto no se filtró para que la historia se viera más limpia — es la misma metodología aplicada a un cuarto período real, y resulta que contradice a los otros tres. La razón: después del piso de octubre de 2022, el Fondo A no protagonizó una recuperación en V. En los 12 meses siguientes, A y E rindieron exactamente lo mismo (+3,0% nominal cada uno), así que no hubo rebote que perderse.

**Corrección a la primera versión de este README**, que atribuía el resultado a que "los bonos también se vendieron ese año por el alza de tasas". En Chile eso pasó en *2021*, no en 2022: el Fondo E cayó 7,3% nominal en 2021, y entre fines de 2021 y el piso de 2022 *subió* 10,2%, en buena parte por la indexación a la UF de sus bonos durante la inflación de ese año. La conclusión no es "cambiarse en pánico siempre cuesta ~25 puntos" — es que el costo es específico a cierta *forma* de crisis (una caída brusca seguida de una recuperación brusca), que es exactamente lo que fueron 2008 y COVID, y lo que 2022 no fue.

## Más allá de 4 ejemplos: todas las caídas reales que hay en los datos

Los cuatro escenarios de arriba se eligieron porque son las crisis que cualquiera que las vivió recuerda por nombre — y eso es un sesgo de selección real: una lista elegida a mano solo contiene las crisis que a alguien se le ocurrió nombrar, y tiende a sobrerrepresentar las más dramáticas y conocidas. `analysis/drawdown_episodes.py` saca al humano de ese paso: escanea todo el índice del Fondo A 2002-2026 de forma programática buscando cada período donde el índice cayó al menos 15% desde un peak anterior y luego se recuperó por completo, sin depender de memoria de "crisis famosas".

Encontró exactamente 3:

| Peak | Valle | Caída real | Recuperado |
|---|---|---|---|
| 2007-10-31 | 2008-11-21 | -43,2% | 2010-11-05 |
| 2011-01-06 | 2011-10-05 | -17,3% | 2013-01-30 |
| 2020-02-24 | 2020-03-24 | -26,5% | 2020-11-25 |

Ojo que el período del alza de tasas 2022 de la tabla de arriba **no** está en esta lista — nunca cruzó una caída del 15% con esta medida, lo cual es consistente (no contradice) con el costo de pánico casi nulo ya encontrado para ese escenario más arriba: una crisis que nunca fue una caída brusca no genera mucho "valle" al cual venderse en pánico.

**En términos reales, sí está.** Deflactado por la UF, 2021–23 es una caída de 26% del poder adquisitivo. Ver [En poder adquisitivo, no en pesos](#en-poder-adquisitivo-no-en-pesos).

`analysis/systematic_panic_switch_cost.py` prueba cada una de estas 3 caídas reales contra una grilla de 5 rezagos de retorno realistas (3/6/12/18/24 meses) — 15 escenarios en total, no 4 — y reporta la distribución completa en vez de anécdotas individuales:

```bash
python analysis/systematic_panic_switch_cost.py     # -> reports/systematic_panic_switch_results.csv
```

| | Valor |
|---|---|
| Escenarios | 15 (3 caídas reales × 5 rezagos de retorno) |
| Costo medio del pánico | **+17,15 pts** |
| Costo mediano del pánico | +12,19 pts |
| Desv. estándar | 10,05 pts |
| Rango | +1,53 a +36,51 pts |
| Pánico peor que quedarse | **100%** de los escenarios |
| Pánico mejor que quedarse | 0% de los escenarios |

Los 15 escenarios sistemáticos favorecieron quedarse — no solo las 3 crisis más conocidas, en todos los rezagos probados. Es una versión más robusta y mecánicamente derivada de la misma conclusión que apuntaban los 4 escenarios elegidos a mano, no una distinta — pero ahora respaldada por cada crisis real que califica en el dataset, no por cuatro elegidas a dedo. Números completos por escenario en `reports/systematic_panic_switch_results.csv`; números agregados en `reports/systematic_panic_switch_summary.json`.

**Una advertencia que este resultado necesita, y que la primera versión de este README no tenía.** Los 15 escenarios se cambian *en el piso*, y el piso solo se conoce después. Elegir el mínimo realizado garantiza por construcción que lo que viene es una subida. Además, solo entran las caídas que se recuperaron: las que nunca vuelven, que son justo las que harían ganar al que se cambió, quedan afuera. Así que este 100% es el peor caso con retrospectiva, no el costo típico del pánico. [El bootstrap de más abajo](#el-piso-es-retrospectivo-cuánto-del-resultado-era-retrospectiva) mide cuánto del resultado era eso.

## "¿Y si me hubiera cambiado *antes*?" — dónde se da vuelta el consejo

Todo lo de arriba fija el cambio **en el piso**, que es lo que significa pánico: huir
después de que la caída ya ocurrió. Pero un lector razonable hace la pregunta obvia:
*¿y si me hubiera movido cuando recién empezaba a caer?*

`analysis/timing_grid.py` la responde, con una decisión de diseño que hace todo el trabajo.

**La variable no es el calendario, es la pérdida ya sufrida.** Barrer por "días antes del
piso" da un resultado tan cierto como inútil: cambiarse una semana después del techo de
2007 gana 90 puntos, porque esquiva el crash entero. Pero nadie sabe que está parado en el
techo — esa combinación mide presciencia, no pánico. Lo que una persona sí observa el día
que decide es cuánto perdió hasta ahí. Así que la grilla se indexa por la caída acumulada
al momento del cambio, lo que convierte la pregunta en una accionable: **si ya perdí X%,
¿todavía conviene moverme?**

481 combinaciones de (día del cambio × plazo de retorno) sobre las 3 caídas reales:

![Dónde deja de servir cambiarse](outputs/figures/punto_de_quiebre.png)

| Pérdida ya sufrida al cambiarse | n | Costo mediano de cambiarse | Gana cambiarse |
|---|---:|---:|---:|
| 0% a −5% | 145 | **−14,0 pp** | 100% |
| −5% a −10% | 123 | **−18,2 pp** | 94% |
| −10% a −20% | 159 | **−10,1 pp** | 74% |
| −20% a −30% | 19 | **+2,9 pp** | 42% |
| más de −30% | 35 | **+16,2 pp** | 29% |

**El punto de quiebre está en torno al −25% ya perdido.** Por debajo, moverse todavía
ayudó en estas caídas; pasado ese punto, costó — y el análisis original anclado al piso es
simplemente el caso extremo de esa última fila, porque cambiarse en el piso es cambiarse
habiendo absorbido el 100% de la caída.

Tres advertencias, porque este resultado es fácil de leer mal:

- **No es una estrategia.** Una zona donde cambiarse gana no es una zona que se pueda
  ocupar: ganar ahí exige saber que la caída va a continuar, que es justo lo que no se sabe
  en el momento. El umbral sirve en la dirección contraria — para decirle a alguien que ya
  perdió mucho que moverse ahora no lo salva.
- **Tres episodios, no tres mil.** Los porcentajes describen estas crisis. El balde de
  −20% a −30% se apoya en 19 combinaciones provenientes del mismo puñado de caídas, así que
  ese 42% pesa muchísimo menos que el 100% de la primera fila.
- **Los baldes no son observaciones independientes.** Las combinaciones dentro de un mismo
  episodio comparten la misma trayectoria de mercado, así que la muestra efectiva se parece
  más a 3 que a 481.

## En poder adquisitivo, no en pesos

Todo lo anterior usa el valor cuota en pesos corrientes, y eso tiene una consecuencia que la primera versión del proyecto no vio: cada retorno lleva la inflación chilena adentro, alrededor de 3,8% al año en la muestra. Para comparar dos fondos en los mismos días eso no importa, porque la inflación se cancela en la razón. Pero una pensión se paga en poder adquisitivo, y apenas el análisis mezcla retornos con sueldos o pensiones, hay que deflactar.

`etl/fetch_uf.py` descarga la UF diaria 2002–2026 (serie del Banco Central, vía el espejo público mindicador.cl) y `etl/build_duckdb.py` construye `fund_index_real`, el mismo índice dividido por la UF.

**Una tercera trampa de datos, peor que las dos anteriores.** La serie de la UF descargada trae tres defectos, y uno solo de ellos lo habría detectado un control puntual:

- **2015-07-11 aparece cinco veces.** Copias idénticas que encajan con sus vecinos: se colapsan. Si dos copias de un día no coincidieran, `etl/parse_uf.py` lo trata como conflicto y falla.
- **Faltan 2015-12-12 y 2015-12-31.** La UF crece a tasa diaria geométrica constante entre el 10 de un mes y el 9 del siguiente, así que la interpolación geométrica reproduce el valor exacto que habría publicado la fórmula.
- **El dólar se coló en la serie.** El 2014-12-29 y el 12-30, la "UF" vale 608,15 y 607,38, que es el *dólar observado* de esos días, en vez de 24.627,10. Deflactar por ese valor hacía saltar el índice real ×40 y volver. Lo encontré perfilando los retornos diarios antes de modelarlos: un día de +370% logarítmico y una curtosis de 4.300. La protección es estructural, no una fecha escrita a mano: la UF no puede moverse 1% en un día (eso sería ~35% de inflación mensual; el mayor movimiento legítimo de la muestra es 0,063% diario, por el IPC de 1,9% de marzo de 2022).

Las tres están fijadas en `tests/test_uf.py`.

**Retorno real anual, sep-2002 a oct-2026:**

| Fondo | Nominal | Real (UF) |
|---|---:|---:|
| A | 9,99% | **5,88%** |
| B | 9,10% | 5,02% |
| C | 8,22% | 4,24% |
| D | 7,27% | 3,26% |
| E | 6,85% | **2,92%** |

El orden A > B > C > D > E es monótono, que es lo que exige el diseño de riesgo del sistema. Es una buena señal de que el deflactado está bien hecho.

**Y en términos reales, las caídas son otras.** El mismo umbral de 15%, aplicado al índice real:

| Máximo | Piso | Caída real | Recuperado en UF |
|---|---|---:|---|
| 2007-11-02 | 2008-11-21 | −48,3% | **2014-08-22** |
| 2020-02-14 | 2020-03-20 | −25,1% | 2021-01-15 |
| 2021-11-19 | 2023-05-05 | **−25,8%** | 2025-08-08 |

![Fondo A en pesos y en UF](outputs/figures/real_vs_nominal.png)

La crisis de 2008 dejó al Fondo A bajo el agua en poder adquisitivo durante casi siete años, no tres. La caída de 2011 desaparece como episodio propio: en UF ocurrió *dentro* del hoyo de la GFC, que todavía no se recuperaba. Y aparece 2021–23, que en pesos llegó a −14,6% y no calificaba: en poder adquisitivo, con la inflación de 12,8% de 2022 encima de la caída del mercado, fue la segunda peor pérdida de los 24 años. Esa es la pérdida de pensiones que la gente efectivamente sintió.

## La pérdida en la pensión, no en puntos

Todo el análisis anterior mide el costo sobre un monto único: cuánto habría crecido un peso que ya estaba adentro. Esa es la pregunta de un inversionista, no la de un afiliado. `analysis/pension_loss.py` simula carreras previsionales completas y mide la pérdida donde importa.

**Supuestos, declarados de frente:**

- Hombre que cotiza 10% de un sueldo de 20 UF (unos $820.000) desde los 25 hasta los 65, con 1% de crecimiento real anual del sueldo.
- **Fondo A hasta los 55 y B desde los 56.** La Ley 19.795 prohíbe el Fondo A para el saldo obligatorio de hombres desde los 56 años y de mujeres desde los 51. Una simulación que deja a alguien de 60 años en el A describe a un afiliado que no puede existir, y la primera versión de este módulo lo hacía.
- Todo en UF. El índice real se usa donde hay datos (2002–2026). Fuera de esa ventana, el retorno real medio de cada fondo. El resultado casi no depende de ese tramo, porque las dos decisiones lo comparten: escalar el retorno extrapolado entre ×0,5 y ×1,5 mueve la pérdida de un afiliado de 40 años solo entre 9,4% y 10,6%.
- El saldo se convierte en pensión con una anualidad cierta de 20 años al 2% real. **No** es una renta vitalicia: no usa tablas de mortalidad ni considera beneficiarios. Sirve para expresar la pérdida en pensión, no para estimar la pensión de nadie. Por la misma razón, el resultado es el **porcentaje**, que no depende del sueldo ni de las lagunas de cotización. Los pesos son ilustrativos.

**Cambio en la pensión, para la misma persona, según cuándo se cambia** (vuelve a su fondo 12 meses después):

| Caída real | 30 años, en el piso | 50 años, en el piso | 50 años, al cruzar −15% |
|---|---:|---:|---:|
| GFC 2008 | −5,1% | −18,5% | **+43,4%** |
| COVID 2020 | −4,5% | −14,2% | −14,2% |
| Inflación 2021–23 | −4,3% | −13,3% | **+18,2%** |

![Cambio en la pensión por edad y por regla](outputs/figures/pension_por_edad.png)

Tres cosas salen de acá:

1. **La pérdida crece con la edad, y es permanente.** Una vez que las dos trayectorias vuelven al mismo fondo crecen igual, así que la recuperación que no se vivió no se recupera nunca. Un afiliado joven la diluye en décadas de cotizaciones posteriores; alguien cerca de jubilar no tiene con qué diluirla.
2. **Mi hipótesis sobre las cotizaciones resultó débil.** Esperaba que dejar de "comprar barato" durante la caída —las cotizaciones que van al E mientras el A está en el piso— fuera una parte grande del costo. El módulo lo separa del efecto sobre el saldo ya acumulado, y explica entre 0% y 14% de la pérdida: doce meses de cotizaciones pesan poco frente a un saldo de décadas.
3. **Cambiarse temprano habría sumado en dos de las tres caídas.** En la GFC, quien salió al cruzar −15% en enero de 2008 esquivó el colapso y volvió cerca del fondo. En COVID las dos reglas coinciden: la caída fue tan rápida que el −15% y el piso cayeron en la misma semana. Pero tres episodios no hacen una estrategia, y la sección siguiente muestra por qué.

**Tres errores que cometí construyendo este módulo, y cómo quedaron fijados.** La primera versión mezclaba un índice nominal con un sueldo real y daba pérdidas de $494.000 mensuales para un sueldo de $800.000. Indexaba cada fondo por su posición desde su propio primer mes, y como el Fondo A empieza en septiembre de 2002 y el E en enero, el precio del E quedaba desfasado ocho meses. Y dejaba a afiliados de 60 años en el Fondo A. Los tres tienen test en `tests/test_pension_loss.py`, y el del desfase lo verifiqué reintroduciendo el error a propósito: dos tests fallan.

## El piso es retrospectivo: cuánto del resultado era retrospectiva

El resultado central de la primera versión del proyecto —"en los 15 escenarios, quedarse ganó"— tiene dos problemas que van más allá de que sean solo 3 caídas:

- **Retrospectiva.** "Cambiarse en el piso" usa el mínimo *realizado* de la caída. Nadie sabe que está en el piso: eso se sabe después. Y elegir el mínimo garantiza por construcción que lo que sigue es una subida.
- **Supervivencia.** Solo entran caídas que se recuperaron. Una caída que nunca vuelve no aparece, y justo esas son las que harían ganar al que se cambió.

`analysis/bootstrap_cost.py` compara dos reglas de pánico:

- **piso**: la del proyecto. Cambio en el mínimo de cada caída de 15% o más que se recuperó.
- **observable**: cambio la primera semana en que la pérdida desde el máximo cruza −15%, ejecutado una semana después, en *toda* caída que lo cruce, se recupere o no. Es lo que una persona puede hacer de verdad.

Y las evalúa en 2.000 historias sintéticas de 24 años generadas con un **bootstrap estacionario** (Politis y Romano, 1994) sobre los retornos semanales reales de A y E. Se remuestrean *bloques* de semanas consecutivas, no semanas sueltas, para conservar lo que hace a una crisis una crisis: el agrupamiento de la volatilidad y la dinámica de caída y rebote. Los dos fondos se remuestrean con los mismos índices, para conservar su correlación. Como el largo del bloque es el parámetro delicado —bloques cortos rompen las recuperaciones en V, que son justamente el mecanismo del costo—, se reporta con tres largos distintos:

| Bloque medio | Regla | Decisiones | Costo mediano | Salir costó | IC 90% del costo medio de una historia |
|---|---|---:|---:|---:|---|
| 13 semanas | piso | 5.158 | +16,4 pp | 95% | [+4,9; +30,1] pp |
| 13 semanas | observable | 5.884 | +3,2 pp | 58% | [−18,4; +17,0] pp |
| 26 semanas | piso | 5.366 | +17,8 pp | 97% | [+6,4; +33,1] pp |
| 26 semanas | observable | 6.041 | +3,4 pp | 59% | [−20,4; +17,7] pp |
| 52 semanas | piso | 5.525 | +21,3 pp | 98% | [+7,6; +35,5] pp |
| 52 semanas | observable | 6.194 | +3,2 pp | 57% | [−26,4; +18,6] pp |

![Distribución del costo según la regla](outputs/figures/bootstrap_reglas.png)

El resultado no depende del largo del bloque. Y en la historia real, la regla observable incluso ganó en 2 de los 3 casos (GFC: −35,1 pp; 2021–23: −13,3 pp; COVID: +28,2 pp).

La lectura honesta ya no es "cambiarse siempre cuesta", sino una **asimetría**: cambiarse tarde, cerca del piso, cuesta caro casi siempre; cambiarse temprano es una apuesta con resultados muy dispersos en las dos direcciones. Lo que esto no resuelve: el bootstrap solo recombina la historia observada, y si 2002–2026 no contiene cierto tipo de crisis, ninguna remuestra la va a producir.

## Series de tiempo: ¿se puede anticipar una caída?

Todo el argumento descansa en que "nadie sabe si la caída va a seguir". Hasta acá eso era un argumento; `analysis/time_series.py` lo somete a prueba formal.

**Estacionariedad.** ADF y KPSS sobre el índice real del Fondo A. Se usan los dos porque sus hipótesis nulas son opuestas:

| Serie | ADF (H0: raíz unitaria) | KPSS (H0: estacionaria) | Lectura |
|---|---:|---:|---|
| log del nivel | p = 0,355 | p ≤ 0,01 | raíz unitaria |
| retornos | p < 0,001 | p ≥ 0,10 | estacionaria |

Se modelan retornos, no precios.

**Predictibilidad: ¿una caída anuncia más caída?**

| Frecuencia | n | AR(1) | t (HAC) | p | Ljung-Box |
|---|---:|---:|---:|---:|---|
| diaria (hábil) | 6.263 | +0,218 | +10,13 | < 0,001 | p ≈ 0 (10 rezagos) |
| **mensual** | 289 | +0,072 | +0,63 | **0,53** | p = 0,34 (12 rezagos) |

La autocorrelación diaria es fuerte, pero es un artefacto conocido de los índices de fondos de pensiones: los activos extranjeros se valorizan con cierres de otros husos horarios y los ilíquidos con retraso. Un afiliado no puede aprovecharla, porque un traspaso se ejecuta días después, al valor cuota de una fecha que no conoce. A la frecuencia que corresponde a la decisión, la mensual, **los retornos no son predecibles**. Después de un mes de −5% o peor (10 casos), el retorno a 12 meses tiene media −1,8% pero mediana +4,8%, y fue positivo en el 60% de las veces, contra 72% incondicional. Con 10 meses que se solapan, la diferencia no alcanza para afirmar nada.

**La volatilidad sí es predecible.** Ljung-Box sobre los retornos al cuadrado y ARCH-LM: p ≈ 0. Un GJR-GARCH(1,1) con errores t de Student da:

| α | γ (asimetría) | β | ν | Persistencia | Vida media de un shock |
|---:|---:|---:|---:|---:|---:|
| 0,046 | **0,065** (t = 4,9) | 0,897 | 8,4 | 0,976 | **28 días hábiles** |

γ significativo es el efecto apalancamiento: las caídas suben la volatilidad más que las subidas del mismo tamaño. Y una vida media de unas seis semanas significa que la tormenta de volatilidad pasa mucho antes de los 12 meses que alguien típicamente se queda afuera.

**La trampa de esta sección: los fines de semana.** La primera corrida del GARCH dio ν clavado en 2,5 y persistencia exactamente 1,0000, idénticos con cuatro especificaciones distintas. Un parámetro que da el mismo valor en cuatro modelos no es un resultado: es el optimizador topando con una cota. La causa era que la Superintendencia publica valor cuota todos los días, y los sábados y domingos el fondo casi no se mueve, porque solo devenga el interés de la renta fija (desviación 43 veces menor que un día hábil). El modelo veía un patrón semanal fijo que no podía ajustar. Ahora los retornos diarios usan solo días hábiles, y el retorno de viernes a lunes incluye el devengo del fin de semana.

**Régimen.** Un modelo Markov-switching de dos estados sobre retornos semanales identifica las crisis desde los datos, sin umbral a dedo:

| Régimen | Media semanal | Volatilidad anual | Duración esperada |
|---|---:|---:|---:|
| calma | +0,23% | 8,0% | ~47 semanas |
| turbulento | −0,33% | 20,0% | ~12 semanas |

Fecha 14 episodios turbulentos, entre ellos mayo de 2006, la GFC, la crisis del euro de 2010 y 2011, el estallido social de 2019, COVID y 2021–22. Pero **"turbulento" no significa "cayendo"**: el modelo detecta volatilidad, no dirección, y dos de los 14 episodios fueron al alza (A +6,0% entre agosto y diciembre de 2020).

![Volatilidad condicional y régimen](outputs/figures/volatilidad_regimen.png)

**¿Se puede usar el régimen para salir a tiempo?** La regla: salir al E cuando la probabilidad de régimen turbulento cruza 0,5 y volver a las 52 semanas, sin contar dos veces el mismo episodio. La primera versión de este cálculo daba que salir *ganaba*, y no lo di por bueno hasta someterlo a dos correcciones. Primero, el rezago real de un traspaso. Segundo, la estimación fuera de muestra: aunque las probabilidades filtradas solo usan el pasado para filtrar, sus parámetros se habían estimado con la muestra completa, futuro incluido. La versión fuera de muestra reestima el modelo cada año, solo con los datos disponibles hasta ese momento.

| Parámetros | Ejecución | Decisiones | Salir costó | La regla rinde | Quedarse en A rinde |
|---|---|---:|---:|---:|---:|
| conocen el futuro | inmediata | 11 | 45% | 6,38%/año | 4,08%/año |
| conocen el futuro | 1 semana después | 11 | 45% | 5,51%/año | 4,08%/año |
| fuera de muestra | inmediata | 12 | 58% | 4,46%/año | 4,08%/año |
| **fuera de muestra** | **1 semana después** | 12 | **58%** | **3,85%/año** | **4,08%/año** |

![La ventaja era información del futuro](outputs/figures/senal_sesgo_anticipacion.png)

La ventaja aparente era casi entera **sesgo de anticipación**. Con 12 decisiones, la diferencia final contra quedarse no se distingue de cero. La conclusión correcta no es "la regla pierde", sino "no hay ventaja una vez que se le quita la información del futuro", y esa es la versión formal de "no es una estrategia que se pueda ocupar".

## ¿El Fondo E es un refugio?

Contra las caídas de la renta variable, sí. En las 12 tormentas del régimen turbulento en que cayó el Fondo A, el E protegió en 10: en la GFC, por ejemplo, el A perdió 15,6% real entre noviembre de 2007 y marzo de 2008 mientras el E ganaba 2,5%. Solo en dos cayeron los dos (junio a noviembre de 2022 y marzo-abril de 2024).

Pero el E tiene su propio riesgo, el de tasas e inflación, y se materializa en otros años:

![Retorno real anual del Fondo E](outputs/figures/fondo_e_anual.png)

- **2021: −13,1% real** (−7,3% nominal con 6,6% de inflación), el mismo año en que el A ganó 13,0%.
- **2026, hasta octubre: −10,5% real** (−7,5% nominal). Antes de creerlo verifiqué que no fuera un artefacto del índice: las siete AFP muestran entre −7,2% y −8,2% en el Fondo E, sin ningún día extremo. Es una caída gradual y sistémica. No conozco su causa y no la atribuyo.

Cambiarse al E no es salir del riesgo. Es cambiar un riesgo por otro.

## Lo que se puede afirmar, y lo que no

**Se puede afirmar:**

- Cambiarse al Fondo E en el piso de una caída cuesta caro casi siempre (97% de las historias sintéticas), y a un afiliado de 50 o 60 años le quita entre 13,1% y 18,5% de la pensión, de forma permanente.
- Los retornos mensuales del Fondo A no son predecibles, y una estrategia basada en detectar turbulencia no tiene ventaja una vez que se le quita la información del futuro.
- Medido en poder adquisitivo, el sistema tuvo una caída de 26% en 2021–23 que el análisis en pesos no registra.

**No se puede afirmar:**

- Que cambiarse temprano sea un error. Es una moneda al aire con un leve sesgo en contra (costó en el 59% de las historias), y en la historia real habría ganado dos de tres veces.
- Que esto describa lo que la gente hizo de verdad. El volumen de traspasos de 2020 no se disparó en el piso (ver más abajo), así que el escenario "cambio en el piso" es una hipótesis sobre el comportamiento, no una observación.

## Calcula tu propio escenario

`scripts/calculator.py` es una calculadora de línea de comandos interactiva: elegí una de las caídas reales detectadas arriba (o ingresá tus propias fechas), elegí a qué fondo te cambiarías en pánico y cuántos meses antes de volver, y calcula el costo histórico real contra los mismos datos que todo lo de arriba — no una regla general.

```bash
python scripts/calculator.py
```

## ¿El comportamiento real de cambio se dispara cerca del valle?

Todo lo anterior responde "cuánto costaría si alguien se cambiara en pánico" — es un contrafactual solo de precios, no evidencia de que la gente realmente lo hace. Así que fui a buscar el comportamiento real: la Superintendencia de Pensiones publica un boletín mensual (`Ficha Estadística Previsional`, un PDF por mes, 164 números archivados desde dic. 2012) que reporta, con 2 meses de rezago, el número real de cuentas traspasadas entre AFP a nivel de todo el sistema ese mes. Descargué 22 de estos boletines — cubriendo una línea base pre-COVID (mediados de 2019), la ventana completa de COVID (2020) y la ventana de alza de tasas 2022 — y extraje ese número real de cada uno.

**Una segunda trampa real de calidad de datos, esta vez en los propios PDF fuente**: la tabla (`Tabla N° 7`) que reporta este número tiene una nota al pie escrita en prosa — *"...traspasadas entre AFP en agosto de 2020 fue de..."* — y en al menos dos de los 22 boletines revisados, esa prosa nombra el mes equivocado (un mes de diferencia en un caso, un año en otro) respecto a lo que dicen los propios encabezados de columna de la tabla. `etl/parse_traspasos.py` no confía en la prosa de la nota al pie para el mes — deriva el mes del encabezado de la tabla (corroborado por todas las demás columnas de esa misma tabla), y solo toma el número de traspasos de la nota al pie. `tests/test_parse_traspasos.py` fija este error exacto con un fixture sintético que lo reproduce.

![Volumen mensual real de traspasos entre AFP](outputs/figures/traspasos_volumen.png)

**Esta es la sorpresa honesta de todo el proyecto**: el volumen de traspasos *no* se dispara en el valle de COVID — *colapsa*, de ~53.000 cuentas/mes a comienzos de 2020 a solo 15.618 en mayo de 2020, para luego rebotar bruscamente a ~50.000 en octubre de 2020. Eso no es evidencia de que la gente no estuviera en pánico — Chile estuvo en cuarentena estricta desde fines de marzo de 2020, las visitas a sucursales de AFP estaban restringidas, y parte del proceso de traspaso todavía no era completamente digital en ese momento, así que el colapso está confundido con la imposibilidad literal de la gente de procesar un cambio, no con que no quisieran hacerlo. El rebote de octubre de 2020 coincide con la flexibilización de la cuarentena y con la controversia política por la primera ley de retiro de fondos previsionales (aprobada en julio de 2020), que puso a las AFP en la contingencia diaria — plausiblemente un gatillo conductual más grande que la propia caída de marzo. La ventana de 2022, en cambio, no muestra ningún movimiento dramático cerca del valle de octubre — consistente con el costo de pánico de ~0 puntos encontrado para ese escenario más arriba: si cambiarse apenas habría costado algo, hay poca razón para esperar un salto en los cambios tampoco.

En resumen: la historia del lado de los precios (cambiarse en pánico en una caída brusca en V es caro) se sostiene bien. La historia del lado del comportamiento (la gente corre a la seguridad justo en el valle) no se sostiene limpiamente en estos datos — el patrón real en 2020 se parece más a "no podía moverse, y se movió una vez que todo reabrió" que a "entró en pánico en el fondo".

## Reproducirlo

```bash
pip install -r requirements.txt
python etl/fetch_valor_cuota.py               # descarga los 5 archivos fuente reales (~7MB)
python etl/parse_valor_cuota.py               # -> data/processed/valor_cuota_long.parquet
python etl/fetch_fichas.py                    # descarga 22 boletines mensuales reales (PDF)
python etl/parse_traspasos.py                 # -> data/processed/traspasos_monthly.parquet
python etl/fetch_uf.py                        # descarga la UF diaria 2002-2026 (Banco Central vía mindicador.cl)
python etl/parse_uf.py                        # limpia duplicados, huecos y el dólar colado -> uf_daily.parquet
python etl/build_duckdb.py                    # -> data/pension_funds.duckdb (incluye fund_index_real, en UF)
python analysis/panic_switch_cost.py          # -> reports/panic_switch_results.csv
python analysis/systematic_panic_switch_cost.py  # -> reports/systematic_panic_switch_results.csv + summary.json
python analysis/timing_grid.py                # -> reports/timing_grid.csv
python analysis/pension_loss.py               # -> reports/pension_loss.csv (pérdida en la pensión, por edad)
python analysis/time_series.py                # -> reports/time_series_summary.json + ts_*.csv (~30 s)
python analysis/bootstrap_cost.py             # -> reports/bootstrap_cost.json (2.000 historias x 3 bloques, ~15 s)
python scripts/make_charts.py                 # -> outputs/figures/*.png (11 figuras)
python scripts/make_interactive_dashboard.py  # -> outputs/interactive/*.html (no commiteado, ver arriba)
python scripts/calculator.py                  # interactivo: tu propio escenario de cambio en pánico
pytest tests/ -v                              # 56 tests, sin necesidad de red (fixtures sintéticas)
```

## Próximos pasos

- **Mujeres.** El modelo de pensión es para un hombre. Para una mujer el corte del Fondo A es a los 51 y la edad legal de jubilación, 60: menos años para diluir una pérdida, así que el costo debería ser mayor a la misma edad.
- **Renta vitalicia de verdad.** Reemplazar la anualidad cierta por una con tablas de mortalidad (RV-2020, CB-2014) y la tasa de venta vigente de cada año.
- **Lagunas de cotización.** No cambian el porcentaje perdido si son uniformes, pero sí si se concentran: quien pierde el empleo en una crisis deja de cotizar justo cuando las cuotas están baratas.
- **El régimen, todo fuera de muestra.** La estrategia de señal ya se evalúa fuera de muestra, pero el fechado de episodios usa la muestra completa.
- **El comportamiento por fondo.** La ventana de 22 boletines cubre COVID y 2022 pero no la GFC de 2008 (la serie de boletines empieza en dic. 2012). Un seguimiento lógico: extender la serie de traspasos y desagregarla por fondo de origen y destino (`Tabla N° 5`, todavía no extraída) para ver si la plata que sí se movió en 2020 fue hacia donde predice la historia del pánico —el Fondo E— o hacia otro lado.

## Autor

Pablo Reyes — Data Scientist, Santiago, Chile.

Licencia: MIT — ver [LICENSE](LICENSE).
