# Indian sector playbook (NSE industry classification)

Sectors follow NSE's own "Industry" field from the Nifty 500 list (20 groups), so every stock
has exactly one sector and the sector numbers are computed from our own price store.
Two kinds of knowledge sit here: **what moves each sector** (stable, below) and **which
sectors are leading now** (measured daily by the screener; the latest snapshot is at the end).

## 1. What moves each sector

| Sector (Nifty 500 count) | Character | Main drivers | Helped by | Hurt by |
|---|---|---|---|---|
| Financial Services (98) | Cyclical, heaviest index weight | Credit growth, net interest margins, asset quality, liquidity | Falling rates (NBFCs most), strong credit demand, FII inflows | Rising bad loans, tight liquidity, FII selling, rate hikes (NBFC funding costs) |
| Capital Goods (69) | Cyclical, high beta | Government and private capex, order books, defence orders | Budget capex, order wins, falling rates | Capex slowdown, execution delays, high valuations |
| Healthcare (44) | Defensive | US generics pricing, USFDA inspections, domestic formulations, hospital occupancy | Weaker rupee (exporters), defensive rotation | USFDA warning letters, US price erosion |
| Automobile and Auto Components (40) | Cyclical | Monthly sales (published on the 1st), rural demand, festive season, EV shift | Good monsoon, rate cuts, falling steel and aluminium | Input cost spikes, weak rural demand |
| Fast Moving Consumer Goods (28) | Defensive, low beta | Volume growth, rural demand, input costs (palm oil, crude derivatives) | Good monsoon, falling input costs, risk-off rotation | Inflation in inputs, weak rural demand |
| Chemicals (26) | Cyclical, export-linked | Global demand, Chinese pricing and dumping, crude-linked feedstock | Weaker rupee, China supply cuts | Chinese dumping, destocking cycles |
| Information Technology (25) | Export, semi-defensive | US and European tech spending, deal wins, quarterly guidance | Weaker rupee, US tech spending recovery, falling US rates | US recession fears, client budget cuts, strong rupee |
| Consumer Services (23) | Discretionary, often richly valued | Urban consumption, retail, travel, food delivery, e-commerce | Strong urban demand, tax cuts | Slowing urban spending, high valuations |
| Metals & Mining (20) | Highly cyclical | China demand, LME and steel prices, import duties | Global commodity upcycle, safeguard duties | China slowdown, global price falls |
| Power (19) | Policy-driven, capex heavy | Power demand (summer peaks), capacity additions, renewables, coal supply | Heatwaves, strong demand, policy support, falling rates | Weak demand, rate rises, coal shortages |
| Oil Gas & Consumable Fuels (19) | Split by sub-type | Crude and gas prices, marketing margins, government pricing | Upstream (ONGC, Oil India): high crude. Refiners/OMCs (BPCL, HPCL, IOC) and gas distributors: falling crude/gas | OMCs: crude spikes. Upstream: crude falls or windfall taxes |
| Consumer Durables (16) | Discretionary | Urban demand, summer (ACs, coolers), festive season | Hot summer, falling copper and steel | Input cost spikes, weak demand |
| Services (14) | Mixed | Trade and logistics volumes, outsourcing | Strong trade and economy | Slowdown |
| Construction (13) | Cyclical, high beta | Infra order inflow, execution, working capital | Budget capex, falling rates | Payment delays, rising rates |
| Realty (11) | Most rate-sensitive | Home loan rates, pre-sales, launches | Rate cuts, strong housing demand | Rate hikes, inventory build-up |
| Construction Materials (11) | Cyclical, seasonal | Cement demand (infra, housing), pricing, fuel costs (pet coke, coal) | Infra push, price hikes, falling fuel | Monsoon quarter (July–September) is seasonally weak |
| Telecommunication (9) | Oligopoly | Tariff hikes, ARPU, capex and debt | Tariff increases | Price wars, heavy spectrum payments |
| Textiles (5) | Export-linked | US and EU orders, cotton prices | Weaker rupee, trade deals | Cotton spikes, weak export demand |
| Media Entertainment & Publication (4) | Small, volatile | Advertising spend, OTT and content | Festive ad spend | Ad slowdowns; very small sample, so treat sector stats with care |
| Diversified (1) | Conglomerate | Its own businesses | — | One stock: sector stats are meaningless |

## 2. Macro shocks: which sectors move

| Shock | Usually helps | Usually hurts |
|---|---|---|
| RBI cuts rates / liquidity eases | Banks and NBFCs, realty, autos, capital goods, construction | (relative) defensives lag |
| RBI hikes / liquidity tight | Defensives: FMCG, pharma, IT | Realty, NBFCs, autos, capex plays |
| Crude oil spikes | Upstream oil (ONGC, Oil India) | OMCs, paints, tyres, aviation, chemicals, FMCG margins; rupee weakens |
| Rupee weakens vs dollar | IT, pharma, textiles, chemicals exporters | Oil importers, electronics importers, companies with dollar debt |
| FII selling wave | — (domestic-flow stocks hold up better) | Large-cap banks, IT and liquid index heavyweights fall first |
| Budget capex push | Capital goods, construction, cement, defence, railways (PSU) | — |
| Good monsoon | Autos (tractors, two-wheelers), FMCG, rural lenders, fertilisers | — |
| China slowdown or dumping | — | Metals, chemicals |
| US recession fears | Domestic plays | IT, export-heavy sectors |

## 3. Sector rotation (tendency, not a rule)

```
Early recovery  -> Financials, autos, realty, consumer discretionary lead
Mid cycle       -> Capital goods, industrials, construction, metals
Late cycle      -> Energy, metals, commodities
Slowdown        -> FMCG, pharma, IT (defensives) hold up best
```
India's rotation is often driven by domestic liquidity (mutual fund SIP flows) and FII flows rather than
the textbook cycle, so the screener trusts measured relative strength over the cycle chart.

## 4. How the screener measures sector strength

Computed daily from the price store, for each of the 20 sectors:

- **Relative strength (RS):** median stock return over 1, 3 and 6 months minus the Nifty 50's return, combined as 40% 1-month, 40% 3-month, 20% 6-month.
- **Breadth:** share of the sector's stocks above their SMA50 and SMA200.
- **RS momentum:** the change in RS over the last 4 weeks.
- **Quadrant** (like a Relative Rotation Graph):

| | RS momentum rising | RS momentum falling |
|---|---|---|
| **RS above Nifty** | **Leading**: favour | **Weakening**: take profits, fewer new entries |
| **RS below Nifty** | **Improving**: early candidates, watch | **Lagging**: avoid new longs |

A stock's sector-strength score is its sector's percentile rank; a leading sector adds points and a lagging sector subtracts.
Sectors with fewer than 5 stocks (Media, Diversified, Textiles) use the stock's own RS instead of sector stats.

## 5. Latest snapshot (measured 21 October 2026, NSE close)

Market regime: **risk-off.** Nifty 50 is 5.6% below its SMA200 and 2.8% below its SMA50 (−2.3% over 1 month,
−5.7% over 3 months). Only 14% of Nifty 500 stocks are above their SMA50 and 33% above their SMA200. India VIX 15.7.

| Sector | Stocks | 1M median | 3M median | % above SMA50 | % above SMA200 | 3M RS vs Nifty |
|---|---|---|---|---|---|---|
| Information Technology | 25 | +9% | +8% | 68% | 58% | **+14%** |
| Media Entertainment & Publication | 4 | 0% | +11% | 50% | 75% | +17% (small sample) |
| Consumer Services | 23 | −4% | −3% | 13% | 48% | +3% |
| Services | 14 | −7% | −7% | 29% | 46% | −1% |
| Automobile and Auto Components | 40 | −8% | −7% | 5% | 28% | −2% |
| Oil Gas & Consumable Fuels | 19 | −4% | −7% | 16% | 35% | −2% |
| Capital Goods | 69 | −10% | −8% | 13% | 43% | −2% |
| Healthcare | 44 | −9% | −9% | 11% | 50% | −3% |
| Metals & Mining | 20 | −9% | −9% | 10% | 6% | −3% |
| Financial Services | 98 | −8% | −9% | 11% | 27% | −3% |
| Fast Moving Consumer Goods | 28 | −4% | −11% | 11% | 21% | −5% |
| Consumer Durables | 16 | −5% | −11% | 12% | 25% | −5% |
| Chemicals | 26 | −8% | −13% | 0% | 27% | −7% |
| Textiles | 5 | −8% | −13% | 20% | 40% | −7% |
| Telecommunication | 9 | −9% | −14% | 33% | 11% | −8% |
| Construction | 13 | −10% | −15% | 0% | 23% | −10% |
| Realty | 11 | −7% | −15% | 0% | 27% | −10% |
| Construction Materials | 11 | −4% | −16% | 9% | 9% | −10% |
| Power | 19 | −7% | −16% | 0% | 18% | −10% |
| Diversified | 1 | −12% | −29% | 0% | 0% | −24% (one stock) |

Reading: IT is the only broad sector leading, consistent with its export earnings and a USD/INR near 94. Rate-sensitive
and capex sectors (power, construction, cement, realty) are weakest. In this regime the screener would show at most
3 picks, from leading sectors, using only the trend-template and momentum setups.

From Phase 2 on, this snapshot is regenerated after every daily update as `D:\TradingAgentsData\screens\sector_snapshot.md`.
