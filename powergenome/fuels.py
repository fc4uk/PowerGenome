"""
Load fuel prices needed for the model
"""

from asyncio.log import logger
import pandas as pd

from powergenome.eia_opendata import add_user_fuel_prices


def fuel_cost_table(fuel_costs, generators, settings):
    all_fuel_costs = add_user_fuel_prices(settings, fuel_costs)
    unique_fuels = generators["Fuel"].drop_duplicates()
    model_year_costs = all_fuel_costs.loc[
        all_fuel_costs["year"] == settings["model_year"], :
    ]
    fuel_df = pd.DataFrame(unique_fuels)

    fuel_price_map = {
        row.full_fuel_name: row.price
        for row in model_year_costs.itertuples(index=False, name="row")
    }

    emission_dict = settings["fuel_emission_factors"]
    user_fuels = set(all_fuel_costs["fuel"]) - set(fuel_costs["fuel"])
    for u_f in user_fuels:
        if u_f not in emission_dict.keys():
            logger.warning(
                "\n\n**********************\n"
                f"The user fuel {u_f} does not have an emissions factor specified in "
                "the settings parameter 'fuel_emission_factors'. This is fine if the "
                "emission factor should be 0, otherwise be sure to add a value.\n"
            )
    fuel_emission_map = {}
    for full_fuel_name in fuel_price_map:
        base_fuel_name = full_fuel_name.split("_")[-1]
        if base_fuel_name in emission_dict:
            fuel_emission_map[full_fuel_name] = emission_dict[base_fuel_name]
        else:
            fuel_emission_map[full_fuel_name] = 0

    ccs_fuels = generators.loc[generators["Fuel"].str.contains("ccs"), "Fuel"].unique()
    for ccs_fuel in ccs_fuels:
        # keep the non-ccs price
        base_name = ("_").join(ccs_fuel.split("_")[:-1])
        fuel_price_map[ccs_fuel] = fuel_price_map[base_name]
        fuel_emission_map[ccs_fuel] = fuel_emission_map[base_name]

    fuel_df["Cost_per_MMBtu"] = fuel_df["Fuel"].map(fuel_price_map)
    fuel_df["CO2_content_tons_per_MMBtu"] = fuel_df["Fuel"].map(fuel_emission_map)

    # Slow to loop through all of the rows this way but the df shouldn't be too long
    fuel_df = fuel_df.apply(adjust_ccs_fuels, axis=1, settings=settings)
    fuel_df = add_carbon_tax(fuel_df, settings)
    fuel_df["Cost_per_MMBtu"] = fuel_df["Cost_per_MMBtu"]
    fuel_df["CO2_content_tons_per_MMBtu"] = fuel_df["CO2_content_tons_per_MMBtu"]
    fuel_df.fillna(0, inplace=True)

    if settings.get("reduce_time_domain"):
        days = settings["time_domain_days_per_period"]
        time_periods = settings["time_domain_periods"]
        num_hours = days * time_periods * 24
    else:
        num_hours = 8760

    fuel_df_prices = pd.DataFrame(
        [fuel_df["Cost_per_MMBtu"]], index=range(1, num_hours + 1)
    )
    fuel_df_prices = fuel_df_prices.round(2)
    fuel_df_prices.columns = unique_fuels

    fuel_df_top = pd.DataFrame([fuel_df["CO2_content_tons_per_MMBtu"]])
    fuel_df_top = fuel_df_top.round(5)
    fuel_df_top.columns = unique_fuels
    fuel_df_top.index = [0]

    fuel_frames = [fuel_df_top, fuel_df_prices]
    fuel_df_new = pd.concat(fuel_frames)
    fuel_df_new.index.name = "Time_Index"
    return fuel_df_new


# def modify_fuel_new_genx():


def adjust_ccs_fuels(ccs_fuel_row, settings):

    if "ccs" in ccs_fuel_row["Fuel"]:

        # USD/tonne disposal
        disposal_cost = settings["ccs_disposal_cost"]

        base_fuel_name = ("_").join(ccs_fuel_row["Fuel"].split("_")[-2:])
        capture_rate = settings["ccs_capture_rate"][base_fuel_name]

        co2_captured = ccs_fuel_row["CO2_content_tons_per_MMBtu"] * capture_rate

        ccs_fuel_row["CO2_content_tons_per_MMBtu"] -= co2_captured
        ccs_fuel_row["Cost_per_MMBtu"] += co2_captured * disposal_cost

    else:
        pass

    return ccs_fuel_row


def add_carbon_tax(fuel_df, settings):

    ctax = settings.get("carbon_tax") or 0

    fuel_df.loc[:, "Cost_per_MMBtu"] = fuel_df.loc[:, "Cost_per_MMBtu"] + (
        fuel_df.loc[:, "CO2_content_tons_per_MMBtu"] * ctax
    )

    return fuel_df
