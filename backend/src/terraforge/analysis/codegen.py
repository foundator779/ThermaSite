from __future__ import annotations

from terraforge.contracts.models import AnalysisPlan

GENERATED_ANALYSIS = r"""from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import linregress, pearsonr


def season(month):
    return "Winter" if month in (12, 1, 2) else "Spring" if month in (3, 4, 5) else "Summer" if month in (6, 7, 8) else "Autumn"


def fit(years, values):
    valid = np.isfinite(years) & np.isfinite(values)
    regression = linregress(years[valid], values[valid])
    return {"slope": float(regression.slope), "p": float(regression.pvalue), "r": float(regression.rvalue), "stderr": float(regression.stderr)}


def style(ax, title, subtitle=""):
    ax.set_title(title, loc="left", fontsize=15, weight="bold", color="#17231f")
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=10.5, color="#69756f")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#dce5df")
    ax.grid(axis="y", color="#edf2ef", linewidth=.8)
    ax.tick_params(colors="#7b8680", labelsize=10)


def main(input_dir, output_dir):
    input_path = Path(input_dir).resolve()
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(input_path / "harmonized_monthly.csv", parse_dates=["date"])
    data["year"] = data.date.dt.year
    data["season"] = data.date.dt.month.map(season)
    data["season_year"] = data.year + (data.date.dt.month == 12).astype(int)

    annual = data.groupby("year", as_index=False).agg(
        local_temperature_c=("local_temperature_c", "mean"),
        regional_temperature_c=("regional_temperature_c", "mean"),
        sea_ice_extent_mkm2=("sea_ice_extent_mkm2", "mean"),
    )
    local_fit = fit(annual.year.to_numpy(), annual.local_temperature_c.to_numpy())
    regional_fit = fit(annual.year.to_numpy(), annual.regional_temperature_c.to_numpy())
    ice_fit = fit(annual.year.to_numpy(), annual.sea_ice_extent_mkm2.to_numpy())

    seasonal = data.groupby(["season", "season_year"], as_index=False).regional_temperature_c.mean()
    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    seasonal_fits = {name: fit(group.season_year.to_numpy(), group.regional_temperature_c.to_numpy()) for name, group in seasonal.groupby("season")}
    fastest = max(seasonal_fits, key=lambda name: seasonal_fits[name]["slope"])
    joined = annual.dropna(subset=["regional_temperature_c", "sea_ice_extent_mkm2"])
    association = pearsonr(joined.regional_temperature_c, joined.sea_ice_extent_mkm2)

    fig, ax = plt.subplots(figsize=(7.3, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.regional_temperature_c, color="#1a7f60", marker="o", markersize=3, linewidth=2, label="Regional mean")
    fitted = regional_fit["slope"] * annual.year + (annual.regional_temperature_c.mean() - regional_fit["slope"] * annual.year.mean())
    ax.plot(annual.year, fitted, color="#e1894b", linewidth=1.6, label="Linear trend")
    style(ax, "Annual temperature trend", f"North Slope regional grid · {regional_fit['slope'] * 10:+.2f} °C/decade")
    ax.set_ylabel("Temperature (°C)")
    ax.legend(frameon=False, fontsize=10)
    fig.tight_layout(); fig.savefig(output_path / "annual_temperature_trend.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    slopes = [seasonal_fits[name]["slope"] * 10 for name in season_order]
    bars = ax.bar(season_order, slopes, color=["#256f8b", "#62a884", "#e2aa58", "#bc765c"], width=.62)
    ax.axhline(0, color="#9ba7a0", linewidth=.8)
    for bar, value in zip(bars, slopes): ax.text(bar.get_x()+bar.get_width()/2, value, f"{value:+.2f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=10)
    style(ax, "Seasonal change", "Regional temperature trend in °C per decade")
    ax.set_ylabel("°C / decade")
    fig.tight_layout(); fig.savefig(output_path / "seasonal_change.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.sea_ice_extent_mkm2, color="#327b9b", linewidth=2, marker="o", markersize=3)
    fitted_ice = ice_fit["slope"] * annual.year + (annual.sea_ice_extent_mkm2.mean() - ice_fit["slope"] * annual.year.mean())
    ax.plot(annual.year, fitted_ice, color="#9ec5d5", linewidth=1.5)
    style(ax, "Arctic sea-ice extent", f"Northern Hemisphere annual mean · {ice_fit['slope'] * 10:+.2f} million km²/decade")
    ax.set_ylabel("Million km²")
    fig.tight_layout(); fig.savefig(output_path / "sea_ice_trend.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.scatter(joined.sea_ice_extent_mkm2, joined.regional_temperature_c, c=joined.year, cmap="viridis", s=38, edgecolor="white", linewidth=.5)
    line = linregress(joined.sea_ice_extent_mkm2, joined.regional_temperature_c)
    xs = np.linspace(joined.sea_ice_extent_mkm2.min(), joined.sea_ice_extent_mkm2.max(), 50)
    ax.plot(xs, line.intercept + line.slope * xs, color="#e1894b", linewidth=1.8)
    style(ax, "Temperature & sea ice", f"Annual paired association · r = {association.statistic:+.2f}, n = {len(joined)}")
    ax.set_xlabel("Sea-ice extent (million km²)"); ax.set_ylabel("Regional temperature (°C)")
    fig.tight_layout(); fig.savefig(output_path / "temperature_sea_ice_association.png", dpi=180); plt.close(fig)

    chart_data = {
        "annual-temperature": {
            "kind": "line", "x_key": "year", "x_label": "Year", "y_label": "Temperature", "unit": "°C",
            "series": [
                {"key": "temperature", "label": "Regional mean", "color": "#1a7f60", "kind": "line"},
                {"key": "trend", "label": "Linear trend", "color": "#e1894b", "kind": "line"},
            ],
            "data": [{"year": int(row.year), "temperature": float(row.regional_temperature_c), "trend": float(value)} for (_, row), value in zip(annual.iterrows(), fitted)],
        },
        "seasonal-change": {
            "kind": "bar", "x_key": "season", "x_label": "Season", "y_label": "Trend", "unit": "°C/decade",
            "series": [{"key": "value", "label": "Temperature trend", "color": "#2c8265", "kind": "bar"}],
            "data": [{"season": name, "value": float(seasonal_fits[name]["slope"] * 10)} for name in season_order],
        },
        "temperature-sea-ice": {
            "kind": "scatter", "x_key": "sea_ice", "y_key": "temperature", "x_label": "Sea-ice extent (million km²)", "y_label": "Regional temperature", "unit": "°C",
            "series": [{"key": "temperature", "label": "Annual paired value", "color": "#327b9b"}],
            "data": [{"year": int(row.year), "sea_ice": float(row.sea_ice_extent_mkm2), "temperature": float(row.regional_temperature_c)} for _, row in joined.iterrows()],
        },
    }

    metrics = {
        "local_temperature_trend_c_per_decade": local_fit["slope"] * 10,
        "local_temperature_p_value": local_fit["p"],
        "regional_temperature_trend_c_per_decade": regional_fit["slope"] * 10,
        "regional_temperature_p_value": regional_fit["p"],
        "sea_ice_trend_mkm2_per_decade": ice_fit["slope"] * 10,
        "sea_ice_p_value": ice_fit["p"],
        "temperature_sea_ice_correlation": float(association.statistic),
        "temperature_sea_ice_p_value": float(association.pvalue),
        "paired_year_count": int(len(joined)),
        "fastest_warming_season": fastest,
        **{f"{name.lower()}_trend_c_per_decade": seasonal_fits[name]["slope"] * 10 for name in season_order},
    }
    result = {
        "status": "success",
        "metrics": metrics,
        "summary_fields": {"period": f"{int(annual.year.min())}–{int(annual.year.max())}", "association_is_causal": False, "chart_data": chart_data},
        "artifacts": [{"path": name, "type": "plot"} for name in ["annual_temperature_trend.png", "seasonal_change.png", "sea_ice_trend.png", "temperature_sea_ice_association.png"]],
        "warnings": ["Correlation is an association and does not establish causation."]
    }
    (output_path / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    main(args.input_dir, args.output_dir)
"""

CUSTOM_HABITAT_ANALYSIS = r"""from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import linregress, pearsonr


def season(month):
    return "Winter" if month in (12, 1, 2) else "Spring" if month in (3, 4, 5) else "Summer" if month in (6, 7, 8) else "Autumn"


def fit(years, values):
    valid = np.isfinite(years) & np.isfinite(values)
    result = linregress(years[valid], values[valid])
    return {"slope": float(result.slope), "p": float(result.pvalue), "r": float(result.rvalue)}


def correlation(left, right):
    valid = np.isfinite(left) & np.isfinite(right)
    if valid.sum() < 3 or np.nanstd(left[valid]) == 0 or np.nanstd(right[valid]) == 0:
        return 0.0
    return float(pearsonr(left[valid], right[valid]).statistic)


def style(ax, title, subtitle=""):
    ax.set_title(title, loc="left", fontsize=15, weight="bold", color="#17231f")
    if subtitle: ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=10, color="#69756f")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#dce5df")
    ax.grid(axis="y", color="#edf2ef", linewidth=.8)
    ax.tick_params(colors="#7b8680", labelsize=9)


def main(input_dir, output_dir):
    output = Path(output_dir).resolve(); output.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(Path(input_dir).resolve() / "harmonized_monthly.csv", parse_dates=["date"])
    data["year"] = data.date.dt.year
    data["season"] = data.date.dt.month.map(season)
    data["season_year"] = data.year + (data.date.dt.month == 12).astype(int)
    annual = data.groupby("year", as_index=False).agg(
        station_temperature_c=("station_temperature_c", "mean"),
        regional_temperature_c=("regional_temperature_c", "mean"),
        station_precipitation_mm=("station_precipitation_mm", "sum"),
        regional_precipitation_mm=("regional_precipitation_mm", "sum"),
    )
    station_temp_fit = fit(annual.year.to_numpy(), annual.station_temperature_c.to_numpy())
    regional_temp_fit = fit(annual.year.to_numpy(), annual.regional_temperature_c.to_numpy())
    precip_fit = fit(annual.year.to_numpy(), annual.regional_precipitation_mm.to_numpy())
    temperature_agreement = correlation(annual.station_temperature_c.to_numpy(), annual.regional_temperature_c.to_numpy())
    precipitation_agreement = correlation(annual.station_precipitation_mm.to_numpy(), annual.regional_precipitation_mm.to_numpy())
    seasonal = data.groupby(["season", "season_year"], as_index=False).regional_temperature_c.mean()
    season_order = ["Winter", "Spring", "Summer", "Autumn"]
    seasonal_fits = {name: fit(group.season_year.to_numpy(), group.regional_temperature_c.to_numpy()) for name, group in seasonal.groupby("season")}
    baseline = annual.iloc[:5]
    recent = annual.iloc[-5:]
    temperature_anomaly = float(recent.regional_temperature_c.mean() - baseline.regional_temperature_c.mean())
    baseline_precip = float(baseline.regional_precipitation_mm.mean())
    precipitation_anomaly_pct = float((recent.regional_precipitation_mm.mean() - baseline_precip) / baseline_precip * 100) if baseline_precip else 0.0
    pressure = "warmer-drier" if temperature_anomaly > 0 and precipitation_anomaly_pct < 0 else "warmer-wetter" if temperature_anomaly > 0 else "cooler-drier" if precipitation_anomaly_pct < 0 else "cooler-wetter"

    ecology_values = data.ecology_payload.dropna() if "ecology_payload" in data.columns else pd.Series(dtype=str)
    ecology = json.loads(ecology_values.iloc[0]) if len(ecology_values) else {}
    species = ecology.get("species", {})
    occurrences = species.get("occurrences", []) if species.get("available") else []
    species_names = sorted({item.get("species") for item in occurrences if item.get("species")})
    occurrence_years = pd.Series([item.get("year") for item in occurrences], dtype="float64").dropna().astype(int)
    observation_by_year = occurrence_years.value_counts().sort_index()

    wildfire = ecology.get("wildfire", {})
    fire_detections = wildfire.get("detections", []) if wildfire.get("available") else []
    total_fire_power = sum(float(item.get("frp") or 0) for item in fire_detections)
    wetlands = ecology.get("wetlands", {})
    wetland_features = wetlands.get("features", []) if wetlands.get("available") else []
    ecological_sources_available = sum(bool(ecology.get(role, {}).get("available")) for role in ("species", "wildfire", "wetlands"))
    ecological_pressure_score = int(temperature_anomaly > 0) + int(precipitation_anomaly_pct < 0) + int(len(fire_detections) > 0)
    ecological_condition = "high pressure" if ecological_pressure_score >= 3 else "watch" if ecological_pressure_score >= 1 else "stable indicators"

    fig, ax = plt.subplots(figsize=(7.3, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.regional_temperature_c, color="#1a7f60", marker="o", markersize=3, linewidth=2, label="NASA regional")
    ax.plot(annual.year, annual.station_temperature_c, color="#739c88", linewidth=1.3, alpha=.8, label="NOAA station ensemble")
    fitted = regional_temp_fit["slope"] * annual.year + (annual.regional_temperature_c.mean() - regional_temp_fit["slope"] * annual.year.mean())
    ax.plot(annual.year, fitted, color="#e1894b", linewidth=1.6, label="Linear trend")
    style(ax, "Selected-area temperature trend", f"{regional_temp_fit['slope'] * 10:+.2f} °C/decade")
    ax.set_ylabel("Temperature (°C)"); ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(output / "area_temperature_trend.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.bar(annual.year, annual.regional_precipitation_mm, color="#5a9ab0", width=.72)
    precip_line = precip_fit["slope"] * annual.year + (annual.regional_precipitation_mm.mean() - precip_fit["slope"] * annual.year.mean())
    ax.plot(annual.year, precip_line, color="#e1894b", linewidth=1.7)
    style(ax, "Selected-area precipitation", f"{precip_fit['slope'] * 10:+.1f} mm/decade · recent anomaly {precipitation_anomaly_pct:+.1f}%")
    ax.set_ylabel("Precipitation (mm/year)")
    fig.tight_layout(); fig.savefig(output / "area_precipitation_trend.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    slopes = [seasonal_fits[name]["slope"] * 10 for name in season_order]
    ax.bar(season_order, slopes, color=["#256f8b", "#62a884", "#e2aa58", "#bc765c"], width=.62)
    ax.axhline(0, color="#9ba7a0", linewidth=.8)
    style(ax, "Seasonal temperature change", "NASA regional trend in °C per decade")
    fig.tight_layout(); fig.savefig(output / "seasonal_change.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.station_temperature_c - annual.station_temperature_c.mean(), label="NOAA", color="#22755a", linewidth=2)
    ax.plot(annual.year, annual.regional_temperature_c - annual.regional_temperature_c.mean(), label="NASA", color="#d98a4b", linewidth=2)
    style(ax, "Independent source agreement", f"Temperature anomaly agreement · r = {temperature_agreement:+.2f}")
    ax.set_ylabel("Temperature anomaly (°C)"); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(output / "climate_source_agreement.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.3, 3.4), facecolor="#fbfdfb")
    if len(observation_by_year): ax.bar(observation_by_year.index, observation_by_year.values, color="#407d62", width=.8)
    style(ax, "Documented species observations", f"{len(species_names)} observed species in the retrieved GBIF sample")
    ax.set_ylabel("Occurrence records")
    fig.tight_layout(); fig.savefig(output / "biodiversity_observations.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.bar(["Recent fire\ndetections", "Mapped wetland\nfeatures"], [len(fire_detections), len(wetland_features)], color=["#d66b45", "#4a8dab"])
    style(ax, "Disturbance and wetland context", "NASA FIRMS and USFWS NWI")
    fig.tight_layout(); fig.savefig(output / "wildfire_wetlands.png", dpi=180); plt.close(fig)

    longitude = float(data.center_longitude.iloc[0]); latitude = float(data.center_latitude.iloc[0])
    geojson = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"indicator":"habitat_climate_pressure","classification":ecological_condition,"climate_classification":pressure,"temperature_anomaly_c":temperature_anomaly,"precipitation_anomaly_pct":precipitation_anomaly_pct},"geometry":{"type":"Point","coordinates":[longitude,latitude]}}]}
    (output / "habitat_change_layer.geojson").write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    species_layer = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{key:value for key,value in item.items() if key != "coordinates"},"geometry":{"type":"Point","coordinates":item["coordinates"]}} for item in occurrences]}
    wildfire_layer = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{key:value for key,value in item.items() if key != "coordinates"},"geometry":{"type":"Point","coordinates":item["coordinates"]}} for item in fire_detections]}
    wetlands_layer = {"type":"FeatureCollection","features":wetland_features}
    for filename, layer in (("species_biodiversity_layer.geojson", species_layer), ("wildfire_layer.geojson", wildfire_layer), ("wetlands_layer.geojson", wetlands_layer)):
        (output / filename).write_text(json.dumps(layer, indent=2), encoding="utf-8")
    chart_data = {
        "area-temperature": {
            "kind": "line", "x_key": "year", "x_label": "Year", "y_label": "Temperature", "unit": "°C",
            "series": [
                {"key": "regional", "label": "NASA regional", "color": "#1a7f60", "kind": "line"},
                {"key": "station", "label": "NOAA stations", "color": "#739c88", "kind": "line"},
                {"key": "trend", "label": "Linear trend", "color": "#e1894b", "kind": "line"},
            ],
            "data": [{"year": int(row.year), "regional": float(row.regional_temperature_c), "station": float(row.station_temperature_c), "trend": float(value)} for (_, row), value in zip(annual.iterrows(), fitted)],
        },
        "area-precipitation": {
            "kind": "composed", "x_key": "year", "x_label": "Year", "y_label": "Annual precipitation", "unit": "mm",
            "series": [
                {"key": "precipitation", "label": "NASA precipitation", "color": "#5a9ab0", "kind": "bar"},
                {"key": "trend", "label": "Linear trend", "color": "#e1894b", "kind": "line"},
            ],
            "data": [{"year": int(row.year), "precipitation": float(row.regional_precipitation_mm), "trend": float(value)} for (_, row), value in zip(annual.iterrows(), precip_line)],
        },
        "source-agreement": {
            "kind": "line", "x_key": "year", "x_label": "Year", "y_label": "Temperature anomaly", "unit": "°C",
            "series": [
                {"key": "noaa", "label": "NOAA", "color": "#22755a", "kind": "line"},
                {"key": "nasa", "label": "NASA", "color": "#d98a4b", "kind": "line"},
            ],
            "data": [{"year": int(row.year), "noaa": float(row.station_temperature_c - annual.station_temperature_c.mean()), "nasa": float(row.regional_temperature_c - annual.regional_temperature_c.mean())} for _, row in annual.iterrows()],
        },
        "species-observations": {
            "kind": "bar", "x_key": "year", "x_label": "Observation year", "y_label": "Occurrence records", "unit": "records",
            "series": [{"key": "observations", "label": "Documented observations", "color": "#407d62", "kind": "bar"}],
            "data": [{"year": int(year), "observations": int(value)} for year, value in observation_by_year.items()],
        },
        "fire-wetlands": {
            "kind": "bar", "x_key": "indicator", "x_label": "Indicator", "y_label": "Retrieved features", "unit": "features",
            "series": [{"key": "value", "label": "Retrieved features", "color": "#4a8dab", "kind": "bar"}],
            "data": [{"indicator": "Fire detections", "value": int(len(fire_detections))}, {"indicator": "Wetland features", "value": int(len(wetland_features))}],
        },
    }
    metrics = {
        "station_temperature_trend_c_per_decade": station_temp_fit["slope"] * 10,
        "regional_temperature_trend_c_per_decade": regional_temp_fit["slope"] * 10,
        "regional_temperature_p_value": regional_temp_fit["p"],
        "regional_precipitation_trend_mm_per_decade": precip_fit["slope"] * 10,
        "regional_precipitation_p_value": precip_fit["p"],
        "recent_temperature_anomaly_c": temperature_anomaly,
        "recent_precipitation_anomaly_pct": precipitation_anomaly_pct,
        "climate_source_agreement": temperature_agreement,
        "precipitation_source_agreement": precipitation_agreement,
        "paired_year_count": int(len(annual)),
        "habitat_pressure_classification": pressure,
        "ecological_condition_classification": ecological_condition,
        "ecological_pressure_score": ecological_pressure_score,
        "ecological_evidence_available_count": ecological_sources_available,
        "observed_species_count": len(species_names),
        "occurrence_record_count": len(occurrences),
        "matched_occurrence_record_count": int(species.get("matched_record_count", 0)),
        "recent_fire_detection_count": len(fire_detections),
        "recent_fire_radiative_power_mw": total_fire_power,
        "nwi_wetland_feature_count": len(wetland_features),
        "nwi_mapped_wetland_acres": float(wetlands.get("mapped_acres_intersecting", 0)),
        **{f"{name.lower()}_trend_c_per_decade": seasonal_fits[name]["slope"] * 10 for name in season_order},
    }
    plot_names = ["area_temperature_trend.png","area_precipitation_trend.png","seasonal_change.png","climate_source_agreement.png","biodiversity_observations.png","wildfire_wetlands.png"]
    layer_names = ["habitat_change_layer.geojson","species_biodiversity_layer.geojson","wildfire_layer.geojson","wetlands_layer.geojson"]
    unavailable = [role for role in ("species", "wildfire", "wetlands") if not ecology.get(role, {}).get("available")]
    warnings = ["Species occurrences reflect documented sampling effort and do not prove population abundance or absence.", "Mapped ecological indicators characterize pressure and context; they do not prove ecological harm or causation."]
    if unavailable: warnings.append("Unavailable evidence roles: " + ", ".join(unavailable))
    result = {"status":"success","metrics":metrics,"summary_fields":{"period":f"{annual.year.min()}–{annual.year.max()}","association_is_causal":False,"ecological_sources_available":ecological_sources_available,"chart_data":chart_data},"artifacts":[{"path":name,"type":"plot"} for name in plot_names] + [{"path":name,"type":"geojson"} for name in layer_names],"warnings":warnings}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--input-dir", required=True); parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(); main(args.input_dir, args.output_dir)
"""


WETLAND_ANALYSIS = r"""from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import linregress, pearsonr


def fit(years, values):
    valid = np.isfinite(years) & np.isfinite(values)
    result = linregress(years[valid], values[valid])
    return {"slope": float(result.slope), "p": float(result.pvalue), "r": float(result.rvalue)}


def style(ax, title, subtitle=""):
    ax.set_title(title, loc="left", fontsize=15, weight="bold", color="#17231f")
    if subtitle: ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=10, color="#69756f")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["bottom", "left"]].set_color("#dce5df")
    ax.grid(axis="y", color="#edf2ef", linewidth=.8)
    ax.tick_params(colors="#7b8680", labelsize=9)


def main(input_dir, output_dir):
    output = Path(output_dir).resolve(); output.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(Path(input_dir).resolve() / "harmonized_monthly.csv", parse_dates=["date"])
    data["year"] = data.date.dt.year
    annual = data.groupby("year", as_index=False).agg(
        water_level_ft=("water_level_ft", "mean"),
        station_temperature_c=("station_temperature_c", "mean"),
        regional_temperature_c=("regional_temperature_c", "mean"),
        station_precipitation_mm=("station_precipitation_mm", "sum"),
        regional_precipitation_mm=("regional_precipitation_mm", "sum"),
    )
    water_fit = fit(annual.year.to_numpy(), annual.water_level_ft.to_numpy())
    station_temp_fit = fit(annual.year.to_numpy(), annual.station_temperature_c.to_numpy())
    regional_temp_fit = fit(annual.year.to_numpy(), annual.regional_temperature_c.to_numpy())
    climate_agreement = pearsonr(annual.station_temperature_c, annual.regional_temperature_c)
    precip_agreement = pearsonr(annual.station_precipitation_mm, annual.regional_precipitation_mm)
    precip_water = pearsonr(annual.regional_precipitation_mm, annual.water_level_ft)

    baseline_years = sorted(annual.year.unique())[:5]
    recent_years = sorted(annual.year.unique())[-5:]
    baseline = data[data.year.isin(baseline_years)]
    recent = data[data.year.isin(recent_years)]
    dry_threshold = float(baseline.water_level_ft.quantile(.25))
    baseline_dry = float((baseline.water_level_ft < dry_threshold).mean())
    recent_dry = float((recent.water_level_ft < dry_threshold).mean())
    water_anomaly = float(recent.water_level_ft.mean() - baseline.water_level_ft.mean())
    dry_change = recent_dry - baseline_dry

    fig, ax = plt.subplots(figsize=(7.3, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.water_level_ft, color="#247596", marker="o", linewidth=2)
    fitted = water_fit["slope"] * annual.year + (annual.water_level_ft.mean() - water_fit["slope"] * annual.year.mean())
    ax.plot(annual.year, fitted, color="#e1894b", linewidth=1.6)
    style(ax, "Everglades annual water level", f"USGS Everglades 1 · {water_fit['slope'] * 10:+.2f} ft/decade")
    ax.set_ylabel("Mean gage height (ft)"); fig.tight_layout(); fig.savefig(output / "annual_water_level.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    bars = ax.bar(["Water-level\nanomaly", "Dry-month\nchange"], [water_anomaly, dry_change], color=["#287f97", "#d99a55"])
    ax.axhline(0, color="#9ba7a0", linewidth=.8)
    for bar, value in zip(bars, [water_anomaly, dry_change]): ax.text(bar.get_x()+bar.get_width()/2, value, f"{value:+.2f}", ha="center", va="bottom" if value >= 0 else "top")
    style(ax, "Wetland habitat-pressure indicators", f"First five years versus latest five years · dry threshold {dry_threshold:.2f} ft")
    fig.tight_layout(); fig.savefig(output / "wetland_habitat_pressure.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.scatter(annual.regional_precipitation_mm, annual.water_level_ft, c=annual.year, cmap="viridis", s=38)
    line = linregress(annual.regional_precipitation_mm, annual.water_level_ft)
    xs = np.linspace(annual.regional_precipitation_mm.min(), annual.regional_precipitation_mm.max(), 50)
    ax.plot(xs, line.intercept + line.slope * xs, color="#e1894b")
    style(ax, "Precipitation & wetland water level", f"Annual association · r = {precip_water.statistic:+.2f}")
    ax.set_xlabel("NASA precipitation (mm/year)"); ax.set_ylabel("USGS gage height (ft)")
    fig.tight_layout(); fig.savefig(output / "precipitation_water_level_association.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(5.2, 3.4), facecolor="#fbfdfb")
    ax.plot(annual.year, annual.station_temperature_c - annual.station_temperature_c.mean(), label="NOAA station", color="#22755a", linewidth=2)
    ax.plot(annual.year, annual.regional_temperature_c - annual.regional_temperature_c.mean(), label="NASA regional", color="#d98a4b", linewidth=2)
    style(ax, "Independent climate-source agreement", f"Temperature anomaly agreement · r = {climate_agreement.statistic:+.2f}")
    ax.set_ylabel("Temperature anomaly (°C)"); ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(output / "climate_source_agreement.png", dpi=180); plt.close(fig)

    chart_data = {
        "annual-water-level": {
            "kind": "line", "x_key": "year", "x_label": "Year", "y_label": "Mean gage height", "unit": "ft",
            "series": [
                {"key": "water_level", "label": "Annual water level", "color": "#247596", "kind": "line"},
                {"key": "trend", "label": "Linear trend", "color": "#e1894b", "kind": "line"},
            ],
            "data": [{"year": int(row.year), "water_level": float(row.water_level_ft), "trend": float(value)} for (_, row), value in zip(annual.iterrows(), fitted)],
        },
        "habitat-pressure": {
            "kind": "bar", "x_key": "indicator", "x_label": "Indicator", "y_label": "Change", "unit": "normalized",
            "series": [{"key": "value", "label": "First versus latest five years", "color": "#287f97", "kind": "bar"}],
            "data": [{"indicator": "Water anomaly (ft)", "value": float(water_anomaly)}, {"indicator": "Dry-month change", "value": float(dry_change)}],
        },
        "precipitation-water": {
            "kind": "scatter", "x_key": "precipitation", "y_key": "water_level", "x_label": "Annual precipitation (mm)", "y_label": "Mean gage height", "unit": "ft",
            "series": [{"key": "water_level", "label": "Annual paired value", "color": "#247596"}],
            "data": [{"year": int(row.year), "precipitation": float(row.regional_precipitation_mm), "water_level": float(row.water_level_ft)} for _, row in annual.iterrows()],
        },
    }

    pressure = "drier" if water_anomaly < 0 and dry_change > 0 else "wetter" if water_anomaly > 0 and dry_change < 0 else "mixed"
    geojson = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"indicator":"wetland_habitat_pressure","classification":pressure,"water_level_anomaly_ft":water_anomaly,"dry_month_fraction_change":dry_change},"geometry":{"type":"Point","coordinates":[-80.55,25.34]}}]}
    (output / "habitat_change_layer.geojson").write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    metrics = {
        "water_level_trend_ft_per_decade": water_fit["slope"] * 10,
        "water_level_p_value": water_fit["p"],
        "latest_water_level_anomaly_ft": water_anomaly,
        "dry_month_fraction_change": dry_change,
        "precipitation_water_level_correlation": float(precip_water.statistic),
        "climate_source_agreement": float(climate_agreement.statistic),
        "precipitation_source_agreement": float(precip_agreement.statistic),
        "station_temperature_trend_c_per_decade": station_temp_fit["slope"] * 10,
        "regional_temperature_trend_c_per_decade": regional_temp_fit["slope"] * 10,
        "paired_year_count": int(len(annual)),
        "habitat_pressure_classification": pressure,
    }
    result = {"status":"success","metrics":metrics,"summary_fields":{"period":f"{annual.year.min()}–{annual.year.max()}","association_is_causal":False,"chart_data":chart_data},"artifacts":[{"path":name,"type":"plot"} for name in ["annual_water_level.png","wetland_habitat_pressure.png","precipitation_water_level_association.png","climate_source_agreement.png"]] + [{"path":"habitat_change_layer.geojson","type":"geojson"}],"warnings":["Hydrologic and climate indicators describe habitat pressure, not confirmed ecological harm or causation."]}
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--input-dir", required=True); parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(); main(args.input_dir, args.output_dir)
"""


def generate_analysis_code(plan: AnalysisPlan) -> str:
    if not plan.steps or "result.json" not in plan.expected_artifacts:
        raise ValueError("Analysis plan does not satisfy the execution contract")
    if any(step.operation == "annual_water_level" for step in plan.steps):
        return WETLAND_ANALYSIS
    if any(step.operation == "habitat_climate_pressure" for step in plan.steps):
        return CUSTOM_HABITAT_ANALYSIS
    return GENERATED_ANALYSIS
