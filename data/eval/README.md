# Photo evaluation set

35 openly licensed photos from Wikimedia Commons, used to evaluate what a vision model reads from a citizen's
photo. Images are not stored in git (`data/eval/photos/` is gitignored); re-download them with
`uv run python scripts/fetch_eval_photos.py` or from the source pages below.

## Results (Gemini `gemini-flash-latest`, 25 Sep 2026)

| | v1: as first evaluated | v2: brown_turbid dropped from photos |
|---|---|---|
| Polluted photos → positive observation | 93% (14/15) | 93% (13/14) |
| Clean photos → false alarm | 40% (4/10) | 8% (1/12) |
| Satellite / no-water images kept out | 100% (7/7) | 100% (7/7) |
| Real stream photos admitted | 100% (28/28) | 100% (28/28) |

Full reports: [v1](report-gemini-v1.md), [v2](report-gemini.md). Raw model outputs: `results-gemini.json`.

**Read these numbers with care:**

- Labels are the developer's, from each photo and its Commons description, and are not expert-verified. Several
  brown-water negatives (tidal shoreline) are debatable.
- v2 is **in-sample**: the brown_turbid exclusion was chosen after seeing these photos, so it is optimistic.
- Grey or milky water, the most important sewage signal, has only one example here (a colour-shifted 1970s slide),
  and the model missed it. A proper evaluation needs real, recent outfall photos, ideally labelled by OAH ecologists.
- 35 photos is a smoke test, not a validation.

## Sources and licences

| id | in scope | label note | licence | author | source |
|---|---|---|---|---|---|
| outfall-01 | yes | Shoreline at wet-weather discharge sign, no visible discharge | CC BY-SA 4.0 | Tdorante10 | [Commons](https://commons.wikimedia.org/wiki/File:Gantry_Plaza_td_(2019-06-08)_037_-_Peninsula_Park,_Stage_II.jpg) |
| outfall-02 | yes | Shoreline at discharge point, no visible discharge | CC BY-SA 4.0 | Tdorante10 | [Commons](https://commons.wikimedia.org/wiki/File:Gantry_Plaza_td_(2019-06-08)_056.jpg) |
| outfall-03 | yes | Shoreline at discharge sign, no visible discharge | CC BY-SA 4.0 | Tdorante10 | [Commons](https://commons.wikimedia.org/wiki/File:Gantry_Plaza_td_(2019-06-08)_054.jpg) |
| foam-01 | yes | Shimna River, foam at rapids (Commons: foam pollution) | CC BY-SA 2.0 | Eric Jones | [Commons](https://commons.wikimedia.org/wiki/File:Foam_pollution_in_the_Shimna_River_at_Tollymore_-_geograph.org.uk_-_6216386.jpg) |
| foam-02 | yes | St. Croix River covered in foam (1970s slide, colour cast) | Public domain | Lee Lockwood | [Commons](https://commons.wikimedia.org/wiki/File:FOAM,_A_SIGN_OF_POLLUTION,_FLOATS_ON_THE_ST._CROIX_RIVER_AT_CALAIS,_DOWN_RIVER_FROM_THE_GEORGIA_PACIFIC_PAPER_MILL_-_NARA_-_550368.jpg) |
| foam-03 | yes | St. Croix River with foam streaks (colour cast) | Public domain | Lee Lockwood | [Commons](https://commons.wikimedia.org/wiki/File:FOAM,_A_SIGN_OF_POLLUTION,_FLOATS_ON_THE_ST._CROIX_RIVER_AT_CALAIS,_DOWN_RIVER_FROM_THE_GEORGIA_PACIFIC_PAPER_MILL_-_NARA_-_550366.jpg) |
| green-01 | no | Satellite image of reservoir bloom | CC BY 4.0 | Copernicus Sentinel-2 imagery, EK - GD DEFIS, EC - DG DEFIS, | [Commons](https://commons.wikimedia.org/wiki/File:Frozen_algal_bloom_in_Lipno_Reservoir,_Czech_Republic_(P-068879-00-06).jpg) |
| green-02 | yes | Algae-greened river with geese | CC BY-SA 3.0 | Daniel Case | [Commons](https://commons.wikimedia.org/wiki/File:Canada_geese_in_algae-greened_Wallkill_River,_Walden,_NY.jpg) |
| green-03 | yes | Aerial photo, algae in bay (Commons description; colour cast) | Public domain | Ted Rozumalski | [Commons](https://commons.wikimedia.org/wiki/File:ALGAE_COLLECTS_IN_SIDE_BAY_OF_THE_FOX_RIVER_BETWEEN_APPLETON_AND_GREEN_BAY_-_NARA_-_550885.jpg) |
| turbid-01 | no | Satellite image of flood | Public domain | NASA | [Commons](https://commons.wikimedia.org/wiki/File:2010_Pakistan_flood_Khewali_by_Landsat-5_2010-08-09_big.jpg) |
| turbid-02 | no | Satellite image of flood | CC BY 2.0 | NASA Goddard Space Flight Center from Greenbelt, MD, USA | [Commons](https://commons.wikimedia.org/wiki/File:Red_River_Flooding_in_North_Dakota_(high_res)_(4455124807).jpg) |
| turbid-03 | no | Satellite image of floodplain | Public domain | ISS Expedition 27 crew | [Commons](https://commons.wikimedia.org/wiki/File:Paran%C3%A1_River_Floodplain,_Northern_Argentina.jpg) |
| clean-01 | yes | Road embankment with culvert outlet, no water visible | Public domain | U.S. Forest Service- Pacific Northwest Region | [Commons](https://commons.wikimedia.org/wiki/File:Stream_restoration_Clear_Creek,_Malheur_National_Forest_(35502377764).jpg) |
| clean-02 | yes | Culvert with pooled dark water | Public domain | U.S. Forest Service- Pacific Northwest Region | [Commons](https://commons.wikimedia.org/wiki/File:Stream_restoration_Clear_Creek,_Malheur_National_Forest_(35941498950).jpg) |
| clean-04 | yes | Urban river park, calm water | CC BY 2.5 | מיכל פריימן | [Commons](https://commons.wikimedia.org/wiki/File:92153_nahal_hadera_park_PikiWiki_Israel.jpg) |
| clean-05 | yes | Urban river park from above | CC BY 2.5 | מיכל פריימן | [Commons](https://commons.wikimedia.org/wiki/File:92152_nahal_hadera_park_PikiWiki_Israel.jpg) |
| outfall-04 | yes | Beach storm-drain outlets, dry | CC BY-SA 4.0 | Ekecdnkoewihdouuepiw | [Commons](https://commons.wikimedia.org/wiki/File:Rio_Monterroso_Estepona_Malaga.jpg) |
| fish-01 | yes | Dead fish in brown water | CC BY-SA 4.0 | Gannu03 | [Commons](https://commons.wikimedia.org/wiki/File:Dead_Fish_in_a_River_2.jpg) |
| fish-02 | yes | Dead fish in river | CC BY-SA 4.0 | Gannu03 | [Commons](https://commons.wikimedia.org/wiki/File:Dead_Fish_in_a_River_6.jpg) |
| outfall-05 | no | Underside of a sewer aqueduct, no water | CC BY-SA 4.0 | Briantist | [Commons](https://commons.wikimedia.org/wiki/File:Northern_Outfall_Sewer_(Greenway)_over_Manor_Road_A1011.jpg) |
| outfall-06 | yes | Distant storm sewer outfall across a river | CC BY-SA 4.0 | Monica Morrison | [Commons](https://commons.wikimedia.org/wiki/File:Storm_sewer_outfall_Saskatoon.jpg) |
| outfall-07 | no | Underside of a sewer aqueduct, no water | CC BY 4.0 | Matt Brown | [Commons](https://commons.wikimedia.org/wiki/File:Northern_Outfall_Sewer_2025-08-17.jpg) |
| outfall-08 | yes | Untreated sewage plume in Moose River (colour cast) | Public domain | Anne LaBastille | [Commons](https://commons.wikimedia.org/wiki/File:DISCHARGE_OF_UNTREATED_SEWAGE_EFFLUENT_INTO_THE_MOOSE_RIVER_FROM_THE_PRIMARY_TREATMENT_PLANT_BELOW_THE_TOWN_OF_OLD..._-_NARA_-_554623.jpg) |
| outfall-09 | yes | Industrial effluent pouring into river | Public domain | Schaefer, Harry, Photographer (NARA record: 8464469) | [Commons](https://commons.wikimedia.org/wiki/File:EFFLUENT_POURS_FROM_THE_SOUTH_CHARLESTON_UNION_CARBIDE_PLANT_INTO_THE_KANAWHA_RIVER._SOME_OF_THIS_DISCHARGE_IS_WATER..._-_NARA_-_551180.jpg) |
| grey-01 | yes | Mula River with white foam patches | CC BY-SA 4.0 | Manshulad | [Commons](https://commons.wikimedia.org/wiki/File:Mula_River_near_Vishrantwadi.jpg) |
| grey-02 | yes | Columbia River, foam among rocks | CC BY 4.0 | Thayne Tuason | [Commons](https://commons.wikimedia.org/wiki/File:Columbia_River_in_East_Wenatchee-_foamy_pollution.jpg) |
| grey-03 | yes | Fish kill (colour cast) | Public domain | French, WL, U.S. Fish and Wildlife Service | [Commons](https://commons.wikimedia.org/wiki/File:Water_pollution_fish_kill.jpg) |
| grey-04 | yes | River choked with litter; litter is not a sewage feature | CC0 | ODC-SIERRA-LEONE | [Commons](https://commons.wikimedia.org/wiki/File:Polluted_river_(Climate_change).jpg) |
| grey-05 | yes | River bank with litter | CC0 | ODC-SIERRA-LEONE | [Commons](https://commons.wikimedia.org/wiki/File:Polluted_river_bank_(Climate_change).jpg) |
| grey-06 | yes | Polluted river bank, water distant | CC BY-SA 4.0 | Bagdane Kailas | [Commons](https://commons.wikimedia.org/wiki/File:Highly_polluted_Mutha_River_at_Kavadipat.jpg) |
| turbid-04 | yes | Mekong flood, muddy brown water | CC BY-SA 4.0 | Basile Morin | [Commons](https://commons.wikimedia.org/wiki/File:Flooded_building_and_tree_trunk_in_the_muddy_water_of_the_Mekong_in_Si_Phan_Don,_Laos,_September_2019.jpg) |
| turbid-05 | no | Road sign reading MUDDY RIVER, no water in view | Public domain | Charles O'Rear | [Commons](https://commons.wikimedia.org/wiki/File:MUDDY_RIVER_AND_HIGHWAY_CROSSING_-_NARA_-_549010.jpg) |
| turbid-06 | yes | Muddy River (Nevada): despite the name, clear water | CC BY-SA 3.0 | Stan Shebs | [Commons](https://commons.wikimedia.org/wiki/File:Muddy_River_upper_1.jpg) |
| grey-07 | yes | Sewage fungus, River Crane | CC BY-SA 4.0 | Extonben | [Commons](https://commons.wikimedia.org/wiki/File:Sewage_fungus_(River_Crane,_England,_UK).jpg) |
| grey-08 | yes | Sphaerotilus natans (sewage fungus) under water | CC BY-SA 3.0 de | Jürgen Mages (import on Commons by Lamiot) | [Commons](https://commons.wikimedia.org/wiki/File:Sphaerotilus_natansD.jpeg) |
