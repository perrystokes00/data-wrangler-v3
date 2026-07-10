```mermaid
graph LR
  app_v3["app_v3"]:::router
  backfill_h3["backfill_h3"]:::module
  backfill_h3_bcp["backfill_h3_bcp"]:::module
  backfill_uwi14["backfill_uwi14"]:::module
  binary_curve_stage["binary_curve_stage"]:::module
  boem_area_codes["boem_area_codes"]:::module
  boem_geo["boem_geo"]:::module
  boem_status_codes["boem_status_codes"]:::module
  bogus_seis["bogus_seis"]:::module
  breakdown["breakdown"]:::module
  build_catalog_mirror["build_catalog_mirror"]:::engine
  build_county_geojson_ND_GOM["build_county_geojson_ND_GOM"]:::module
  build_county_geojson_gom["build_county_geojson_gom"]:::module
  build_county_geojson_nd["build_county_geojson_nd"]:::module
  build_geojson_from_snowflake["build_geojson_from_snowflake"]:::module
  build_well_geojson_old["build_well_geojson_old"]:::module
  bulk_runner["bulk_runner"]:::module
  capture_ran["capture_ran"]:::module
  catalog_capture["catalog_capture"]:::engine
  catalog_docs["catalog_docs"]:::module
  catalog_readiness["catalog_readiness"]:::module
  catalog_scorecard["catalog_scorecard"]:::module
  check_conn["check_conn"]:::module
  check_fixes["check_fixes"]:::module
  check_nd["check_nd"]:::module
  claim_timing["claim_timing"]:::module
  classify_dir["classify_dir"]:::module
  classify_inventory["classify_inventory"]:::module
  clean_null_periods["clean_null_periods"]:::module
  cleanup_repo["cleanup_repo"]:::module
  cleanup_session.p;y["cleanup_session.p;y"]:::module
  clear_catalog["clear_catalog"]:::module
  clear_dlis_wells["clear_dlis_wells"]:::module
  clone_db["clone_db"]:::module
  clone_schema["clone_schema"]:::module
  collect_final_documents["collect_final_documents"]:::module
  colorado_origin["colorado_origin"]:::module
  compare_extract["compare_extract"]:::module
  config["config"]:::module
  copy_reference_data["copy_reference_data"]:::module
  copy_views["copy_views"]:::module
  crawl_bench["crawl_bench"]:::module
  curve_eligibility["curve_eligibility"]:::module
  curve_uwi_now["curve_uwi_now"]:::module
  db_cleanup["db_cleanup"]:::module
  db_health["db_health"]:::module
  debug_survey["debug_survey"]:::module
  dedup_prod_volume["dedup_prod_volume"]:::module
  defrag_queue["defrag_queue"]:::module
  deploy["deploy"]:::module
  deploy_federation["deploy_federation"]:::module
  dev_resume["dev_resume"]:::module
  diag["diag"]:::module
  diag_core_photos["diag_core_photos"]:::module
  diagnose_transport["diagnose_transport"]:::module
  dlis_names["dlis_names"]:::module
  doc_classifier["doc_classifier"]:::module
  doc_join["doc_join"]:::module
  doc_query["doc_query"]:::module
  docs_per_well["docs_per_well"]:::module
  dv_standards_seed["dv_standards_seed"]:::module
  dv_table_loader["dv_table_loader"]:::module
  dw_utils["dw_utils"]:::module
  enrich_file_headers["enrich_file_headers"]:::engine
  enrich_from_dbf["enrich_from_dbf"]:::module
  ensure_catalog_columns["ensure_catalog_columns"]:::module
  entity_seeder["entity_seeder"]:::engine
  errs["errs"]:::module
  errs_full["errs_full"]:::module
  export_bcp["export_bcp"]:::module
  export_for_snowflake["export_for_snowflake"]:::module
  exporters["exporters"]:::module
  extract_core["extract_core"]:::engine
  extract_petro["extract_petro"]:::module
  federation_map["federation_map"]:::module
  file_viewer["file_viewer"]:::module
  find_bad_geom["find_bad_geom"]:::module
  find_field_shp["find_field_shp"]:::module
  fingerprint["fingerprint"]:::module
  fix_core_photos["fix_core_photos"]:::module
  fk_catalog_check["fk_catalog_check"]:::module
  fk_resolution["fk_resolution"]:::module
  function Deploy["function Deploy"]:::module
  gen_schema_docs["gen_schema_docs"]:::module
  gen_synthetic_completions["gen_synthetic_completions"]:::module
  gen_view["gen_view"]:::module
  generate_core_images["generate_core_images"]:::module
  generate_county_boundaries["generate_county_boundaries"]:::module
  generate_dataview_schema["generate_dataview_schema"]:::module
  generate_dataview_testdata["generate_dataview_testdata"]:::module
  generate_db_schema["generate_db_schema"]:::module
  generate_licence["generate_licence"]:::module
  generate_snapshot["generate_snapshot"]:::module
  geo_keys["geo_keys"]:::module
  geography_layers,py["geography_layers,py"]:::module
  geography_layers["geography_layers"]:::module
  gold_match["gold_match"]:::module
  h3_demo["h3_demo"]:::module
  h3_map_test["h3_map_test"]:::module
  hash_keys["hash_keys"]:::module
  index_well_master["index_well_master"]:::module
  ingest_to_snowflake["ingest_to_snowflake"]:::module
  ingest_to_snowflake_fast["ingest_to_snowflake_fast"]:::module
  inspect_bad_wkt["inspect_bad_wkt"]:::module
  inspect_cat_land["inspect_cat_land"]:::module
  inv_workbench["inv_workbench"]:::module
  list_seis_tables["list_seis_tables"]:::module
  load_core_photos["load_core_photos"]:::module
  load_kgs["load_kgs"]:::module
  load_nd_gdb["load_nd_gdb"]:::module
  load_ok_csv["load_ok_csv"]:::module
  load_rrc_maf016["load_rrc_maf016"]:::module
  load_rrc_w1_permits["load_rrc_w1_permits"]:::module
  load_well_master["load_well_master"]:::module
  make_test_dataset["make_test_dataset"]:::module
  make_test_dataset_all["make_test_dataset_all"]:::module
  make_well_shapefile["make_well_shapefile"]:::module
  map_app["map_app"]:::module
  mapping_studio["mapping_studio"]:::module
  migrate_petroleum_regions["migrate_petroleum_regions"]:::module
  migrate_state_regions["migrate_state_regions"]:::module
  missing_files["missing_files"]:::module
  __init__["__init__"]:::module
  audit_log["audit_log"]:::module
  catalog_dialect["catalog_dialect"]:::module
  catalog_rules["catalog_rules"]:::module
  csv_catalog["csv_catalog"]:::module
  curve_registry["curve_registry"]:::module
  db["db"]:::module
  db_dialect["db_dialect"]:::module
  db_pool["db_pool"]:::module
  db_v3["db_v3"]:::module
  delete_util["delete_util"]:::module
  demo_reset["demo_reset"]:::module
  dlis_catalog["dlis_catalog"]:::module
  doc_catalog_store["doc_catalog_store"]:::module
  dv_catalog_adapter["dv_catalog_adapter"]:::module
  dv_office_loader["dv_office_loader"]:::module
  dv_spatial_loader["dv_spatial_loader"]:::module
  entity_map_seed["entity_map_seed"]:::module
  file_header_catalog["file_header_catalog"]:::module
  file_header_store["file_header_store"]:::module
  file_inventory["file_inventory"]:::module
  file_inventory_governance["file_inventory_governance"]:::module
  file_summarizer["file_summarizer"]:::module
  fk["fk"]:::module
  fk_catalog["fk_catalog"]:::module
  fk_catalog_v3["fk_catalog_v3"]:::module
  fk_entity["fk_entity"]:::module
  fk_resolve_panel["fk_resolve_panel"]:::module
  format_library["format_library"]:::module
  gom_dir_srvy_loader["gom_dir_srvy_loader"]:::module
  gom_well_loader["gom_well_loader"]:::module
  h3_grids["h3_grids"]:::module
  h3_map_layer["h3_map_layer"]:::module
  import_hashlib["import_hashlib"]:::module
  inv_auth["inv_auth"]:::module
  inv_email["inv_email"]:::module
  json_well_log_catalog["json_well_log_catalog"]:::module
  las_catalog["las_catalog"]:::module
  las_loader["las_loader"]:::module
  licence["licence"]:::module
  lis_catalog["lis_catalog"]:::module
  mapping["mapping"]:::module
  normalize["normalize"]:::module
  p190_catalog["p190_catalog"]:::module
  page_workbench["page_workbench"]:::page
  patch_dedup["patch_dedup"]:::module
  pdf_db_loader["pdf_db_loader"]:::module
  pdf_survey_catalog["pdf_survey_catalog"]:::module
  ppdm_agent["ppdm_agent"]:::module
  profile_files["profile_files"]:::module
  promote["promote"]:::module
  schema["schema"]:::module
  scout_pdf_reader["scout_pdf_reader"]:::module
  seed_catalog["seed_catalog"]:::module
  segy_catalog["segy_catalog"]:::module
  seis_filename_parser["seis_filename_parser"]:::module
  shapefile_catalog["shapefile_catalog"]:::module
  staging["staging"]:::module
  survey_loader["survey_loader"]:::module
  user_rules["user_rules"]:::module
  validate["validate"]:::module
  value_standardize["value_standardize"]:::module
  witsml_catalog["witsml_catalog"]:::module
  wl_file_map["wl_file_map"]:::module
  nd_gdb["nd_gdb"]:::module
  page_ai_importer["page_ai_importer"]:::page
  page_bulk["page_bulk"]:::page
  page_catalog_search["page_catalog_search"]:::page
  page_data_model["page_data_model"]:::page
  page_db_explorer["page_db_explorer"]:::page
  page_dv_catalog["page_dv_catalog"]:::page
  page_extraction_inspector["page_extraction_inspector"]:::page
  page_fed_loader["page_fed_loader"]:::page
  page_federation_search["page_federation_search"]:::page
  page_file_browser["page_file_browser"]:::page
  page_file_catalog["page_file_catalog"]:::page
  page_file_catalog_v3["page_file_catalog_v3"]:::page
  page_file_inventory["page_file_inventory"]:::page
  page_file_inventory_gov["page_file_inventory_gov"]:::page
  page_file_manager["page_file_manager"]:::page
  page_file_workbench["page_file_workbench"]:::page
  page_import_gom["page_import_gom"]:::page
  page_import_gom_dir_srvy["page_import_gom_dir_srvy"]:::page
  page_import_osdu["page_import_osdu"]:::page
  page_import_rrc["page_import_rrc"]:::page
  page_import_rrc_shp["page_import_rrc_shp"]:::page
  page_import_shapefile["page_import_shapefile"]:::page
  page_import_witsml["page_import_witsml"]:::page
  page_las["page_las"]:::page
  page_licence["page_licence"]:::page
  page_mapping_studio["page_mapping_studio"]:::page
  page_monitor["page_monitor"]:::page
  page_pipeline["page_pipeline"]:::page
  page_pipeline_old["page_pipeline_old"]:::page
  page_pipeline_tools (1)["page_pipeline_tools (1)"]:::page
  page_pipeline_tools["page_pipeline_tools"]:::page
  page_pipeline_v3["page_pipeline_v3"]:::page
  page_ppdm_map["page_ppdm_map"]:::page
  page_region_builder["page_region_builder"]:::page
  page_rules["page_rules"]:::page
  page_schema_overview["page_schema_overview"]:::page
  page_seed["page_seed"]:::page
  page_selected_documents ["page_selected_documents "]:::page
  page_selected_documents["page_selected_documents"]:::page
  page_shapefile_catalog["page_shapefile_catalog"]:::page
  page_splash["page_splash"]:::page
  page_standards_manager["page_standards_manager"]:::page
  page_triage["page_triage"]:::page
  page_vault["page_vault"]:::page
  page_well_documents (11)["page_well_documents (11)"]:::page
  page_well_documents["page_well_documents"]:::page
  page_well_map - Copy["page_well_map - Copy"]:::page
  page_well_map["page_well_map"]:::page
  page_well_map3clusters["page_well_map3clusters"]:::page
  page_well_map_baseline_2["page_well_map_baseline_2"]:::page
  page_well_map_docs["page_well_map_docs"]:::page
  page_well_map_save2["page_well_map_save2"]:::page
  page_well_mapa_save["page_well_mapa_save"]:::page
  page_wl_map_old["page_wl_map_old"]:::page
  parallel_crawl["parallel_crawl"]:::module
  path_identity["path_identity"]:::module
  pending_detail["pending_detail"]:::module
  petroleum_regions["petroleum_regions"]:::module
  pipeline_proc_runner["pipeline_proc_runner"]:::module
  pipeline_profiler["pipeline_profiler"]:::module
  pipeline_run (22)["pipeline_run (22)"]:::module
  pipeline_run["pipeline_run"]:::engine
  poc_area_sanity["poc_area_sanity"]:::module
  poc_geog_area["poc_geog_area"]:::module
  poc_geog_fix["poc_geog_fix"]:::module
  poc_seis3d_geom["poc_seis3d_geom"]:::module
  populate_dv_well_protraction_area["populate_dv_well_protraction_area"]:::module
  populate_h3["populate_h3"]:::module
  prep_rrc_texas["prep_rrc_texas"]:::module
  profile_capture["profile_capture"]:::module
  project_map["project_map"]:::module
  promote_catalog["promote_catalog"]:::engine
  promote_las_catalog_fast["promote_las_catalog_fast"]:::module
  promote_timing["promote_timing"]:::module
  provenance_audit["provenance_audit"]:::module
  real_link_path["real_link_path"]:::module
  recatalog_seis["recatalog_seis"]:::module
  ref_seeder["ref_seeder"]:::module
  refresh_demo_grids["refresh_demo_grids"]:::module
  remaining_shp["remaining_shp"]:::module
  reset_catalog["reset_catalog"]:::module
  resolve_log_identity["resolve_log_identity"]:::module
  run_fixture_triage["run_fixture_triage"]:::module
  run_promote["run_promote"]:::module
  run_stage["run_stage"]:::module
  schema_cache["schema_cache"]:::module
  schema_introspect["schema_introspect"]:::module
  score_inventory_batch_fast["score_inventory_batch_fast"]:::module
  seed_las_catalog["seed_las_catalog"]:::module
  seed_political["seed_political"]:::module
  seed_queue["seed_queue"]:::module
  seed_references["seed_references"]:::module
  segy_header["segy_header"]:::engine
  seis_line_cols["seis_line_cols"]:::module
  seis_when["seis_when"]:::module
  setup_database["setup_database"]:::module
  setup_dataview["setup_dataview"]:::module
  setup_wranglerview["setup_wranglerview"]:::module
  shp_to_protraction_geojson["shp_to_protraction_geojson"]:::module
  shrink_log["shrink_log"]:::module
  skip_detail["skip_detail"]:::module
  skips["skips"]:::module
  slow_files["slow_files"]:::module
  spatial_seeder["spatial_seeder"]:::module
  stage_timer["stage_timer"]:::module
  standardize_well_attrs["standardize_well_attrs"]:::module
  state_regions["state_regions"]:::module
  test_pipeline["test_pipeline"]:::module
  test_vault_layout["test_vault_layout"]:::module
  time_shp_outline["time_shp_outline"]:::module
  trace_field["trace_field"]:::module
  trace_link_gap["trace_link_gap"]:::module
  trace_nulls["trace_nulls"]:::module
  trace_pipeline["trace_pipeline"]:::module
  trace_pipeline2["trace_pipeline2"]:::module
  triage_inventory["triage_inventory"]:::module
  ui_helpers["ui_helpers"]:::module
  upload_ok["upload_ok"]:::module
  upload_to_snowflake["upload_to_snowflake"]:::module
  us_geo["us_geo"]:::module
  uwi_errs["uwi_errs"]:::module
  uwi_format["uwi_format"]:::module
  validate_h3_backfill["validate_h3_backfill"]:::module
  validate_h3_views["validate_h3_views"]:::module
  validate_v_well["validate_v_well"]:::module
  vault_copy["vault_copy"]:::module
  vault_organizer["vault_organizer"]:::engine
  vault_run["vault_run"]:::module
  verify_model_a["verify_model_a"]:::module
  verify_seis_run["verify_seis_run"]:::module
  walk_and_load["walk_and_load"]:::module
  walk_bulk["walk_bulk"]:::module
  walk_fast["walk_fast"]:::module
  walk_petroleum["walk_petroleum"]:::module
  walk_test["walk_test"]:::module
  whats_at["whats_at"]:::module
  why_pending["why_pending"]:::module
  work_queue["work_queue"]:::module
  worker_core["worker_core"]:::engine
  worker_pool["worker_pool"]:::module
  app_v3 --> db
  app_v3 --> demo_reset
  app_v3 --> dv_spatial_loader
  app_v3 --> page_db_explorer
  app_v3 --> page_extraction_inspector
  app_v3 --> page_file_catalog
  app_v3 --> page_file_manager
  app_v3 --> page_monitor
  app_v3 --> page_pipeline
  app_v3 --> page_region_builder
  app_v3 --> page_schema_overview
  app_v3 --> page_standards_manager
  app_v3 --> page_triage
  app_v3 --> page_well_documents
  app_v3 --> page_well_map
  app_v3 --> page_workbench
  app_v3 --> schema
  backfill_uwi14 --> worker_core
  binary_curve_stage --> catalog_capture
  binary_curve_stage --> lis_catalog
  bogus_seis --> worker_core
  breakdown --> worker_core
  bulk_runner --> mapping
  bulk_runner --> page_bulk
  bulk_runner --> schema
  bulk_runner --> staging
  capture_ran --> worker_core
  catalog_readiness --> build_catalog_mirror
  catalog_readiness --> db
  claim_timing --> work_queue
  claim_timing --> worker_core
  classify_dir --> doc_classifier
  classify_inventory --> doc_classifier
  clean_null_periods --> worker_core
  clear_catalog --> build_catalog_mirror
  clear_dlis_wells --> worker_core
  colorado_origin --> worker_core
  compare_extract --> worker_core
  crawl_bench --> parallel_crawl
  crawl_bench --> worker_core
  curve_eligibility --> worker_core
  curve_uwi_now --> worker_core
  db_cleanup --> worker_core
  db_health --> worker_core
  dedup_prod_volume --> worker_core
  dev_resume --> db
  dev_resume --> mapping
  dev_resume --> normalize
  dev_resume --> schema
  dev_resume --> staging
  diag --> worker_core
  dlis_names --> worker_core
  doc_join --> worker_core
  doc_query --> worker_core
  docs_per_well --> worker_core
  dv_table_loader --> fk_resolution
  dv_table_loader --> path_identity
  ensure_catalog_columns --> worker_core
  entity_seeder --> hash_keys
  errs --> worker_core
  errs_full --> worker_core
  export_bcp --> exporters
  exporters --> export_bcp
  exporters --> file_viewer
  extract_core --> csv_catalog
  extract_core --> file_summarizer
  extract_core --> json_well_log_catalog
  extract_core --> lis_catalog
  extract_core --> pdf_survey_catalog
  extract_core --> segy_header
  extract_core --> shapefile_catalog
  extract_core --> witsml_catalog
  file_viewer --> p190_catalog
  find_bad_geom --> worker_core
  fk_catalog_check --> dv_table_loader
  gen_schema_docs --> schema_introspect
  gold_match --> worker_core
  index_well_master --> worker_core
  inspect_bad_wkt --> worker_core
  inspect_cat_land --> worker_core
  inv_workbench --> dlis_catalog
  inv_workbench --> file_header_catalog
  inv_workbench --> las_catalog
  inv_workbench --> las_loader
  inv_workbench --> p190_catalog
  inv_workbench --> segy_catalog
  list_seis_tables --> worker_core
  make_test_dataset_all --> file_summarizer
  make_test_dataset_all --> make_test_dataset
  mapping_studio --> dv_table_loader
  migrate_petroleum_regions --> petroleum_regions
  migrate_state_regions --> state_regions
  missing_files --> worker_core
  catalog_rules --> file_summarizer
  catalog_rules --> pdf_survey_catalog
  curve_registry --> dlis_catalog
  curve_registry --> las_catalog
  db --> db_dialect
  db --> db_pool
  db_dialect --> normalize
  db_v3 --> db_dialect
  db_v3 --> db_pool
  dv_office_loader --> catalog_capture
  entity_map_seed --> mapping
  file_header_catalog --> segy_catalog
  file_header_store --> catalog_dialect
  file_header_store --> setup_database
  file_inventory --> catalog_rules
  file_inventory --> fingerprint
  file_summarizer --> json_well_log_catalog
  file_summarizer --> lis_catalog
  file_summarizer --> pdf_survey_catalog
  file_summarizer --> segy_header
  file_summarizer --> shapefile_catalog
  file_summarizer --> witsml_catalog
  fk --> db
  fk_catalog --> db
  fk_catalog --> fk
  fk_catalog_v3 --> db
  fk_catalog_v3 --> fk
  fk_entity --> db
  fk_entity --> fk
  fk_entity --> mapping
  fk_resolve_panel --> fk
  fk_resolve_panel --> value_standardize
  h3_map_layer --> h3_grids
  inv_auth --> audit_log
  inv_auth --> file_inventory_governance
  json_well_log_catalog --> catalog_capture
  mapping --> schema
  normalize --> db
  normalize --> user_rules
  page_workbench --> catalog_capture
  page_workbench --> catalog_readiness
  page_workbench --> catalog_scorecard
  page_workbench --> clear_catalog
  page_workbench --> collect_final_documents
  page_workbench --> dv_office_loader
  page_workbench --> enrich_file_headers
  page_workbench --> extract_core
  page_workbench --> extract_petro
  page_workbench --> file_viewer
  page_workbench --> fingerprint
  page_workbench --> json_well_log_catalog
  page_workbench --> page_monitor
  page_workbench --> page_triage
  page_workbench --> page_vault
  page_workbench --> path_identity
  page_workbench --> pdf_db_loader
  page_workbench --> pdf_survey_catalog
  page_workbench --> pipeline_run
  page_workbench --> promote_catalog
  page_workbench --> segy_header
  page_workbench --> shapefile_catalog
  page_workbench --> vault_organizer
  page_workbench --> witsml_catalog
  pdf_db_loader --> catalog_capture
  pdf_db_loader --> pdf_survey_catalog
  pdf_db_loader --> survey_loader
  pdf_survey_catalog --> scout_pdf_reader
  profile_files --> worker_core
  promote --> db
  promote --> mapping
  promote --> schema
  promote --> validate
  seed_catalog --> db
  shapefile_catalog --> catalog_capture
  shapefile_catalog --> catalog_dialect
  staging --> db
  survey_loader --> catalog_capture
  validate --> db
  validate --> user_rules
  witsml_catalog --> catalog_capture
  wl_file_map --> dlis_catalog
  wl_file_map --> las_catalog
  page_bulk --> db
  page_bulk --> fk
  page_bulk --> fk_entity
  page_bulk --> mapping
  page_bulk --> normalize
  page_bulk --> promote
  page_bulk --> staging
  page_bulk --> ui_helpers
  page_bulk --> validate
  page_data_model --> ui_helpers
  page_db_explorer --> db
  page_dv_catalog --> dlis_catalog
  page_dv_catalog --> doc_catalog_store
  page_dv_catalog --> dv_catalog_adapter
  page_dv_catalog --> file_inventory
  page_dv_catalog --> file_summarizer
  page_dv_catalog --> las_catalog
  page_dv_catalog --> page_file_workbench
  page_extraction_inspector --> extract_core
  page_federation_search --> db
  page_federation_search --> db_dialect
  page_file_browser --> db_pool
  page_file_browser --> dlis_catalog
  page_file_browser --> file_header_store
  page_file_browser --> las_catalog
  page_file_browser --> p190_catalog
  page_file_browser --> page_file_workbench
  page_file_browser --> segy_catalog
  page_file_browser --> seis_filename_parser
  page_file_catalog --> collect_final_documents
  page_file_catalog --> enrich_file_headers
  page_file_catalog --> file_summarizer
  page_file_catalog --> path_identity
  page_file_catalog --> pdf_db_loader
  page_file_catalog --> pdf_survey_catalog
  page_file_catalog --> shapefile_catalog
  page_file_catalog --> vault_copy
  page_file_catalog_v3 --> audit_log
  page_file_catalog_v3 --> dlis_catalog
  page_file_catalog_v3 --> file_header_catalog
  page_file_catalog_v3 --> file_header_store
  page_file_catalog_v3 --> file_inventory
  page_file_catalog_v3 --> file_inventory_governance
  page_file_catalog_v3 --> file_summarizer
  page_file_catalog_v3 --> inv_auth
  page_file_catalog_v3 --> inv_email
  page_file_catalog_v3 --> inv_workbench
  page_file_catalog_v3 --> las_catalog
  page_file_catalog_v3 --> p190_catalog
  page_file_catalog_v3 --> page_dv_catalog
  page_file_catalog_v3 --> page_file_browser
  page_file_catalog_v3 --> segy_catalog
  page_file_catalog_v3 --> seis_filename_parser
  page_file_inventory --> audit_log
  page_file_inventory --> dlis_catalog
  page_file_inventory --> file_header_catalog
  page_file_inventory --> file_header_store
  page_file_inventory --> file_inventory
  page_file_inventory --> file_inventory_governance
  page_file_inventory --> file_summarizer
  page_file_inventory --> inv_auth
  page_file_inventory --> inv_email
  page_file_inventory --> inv_workbench
  page_file_inventory --> las_catalog
  page_file_inventory --> p190_catalog
  page_file_inventory --> page_file_browser
  page_file_inventory --> page_shapefile_catalog
  page_file_inventory --> segy_catalog
  page_file_inventory --> seis_filename_parser
  page_file_inventory_gov --> audit_log
  page_file_inventory_gov --> dlis_catalog
  page_file_inventory_gov --> file_header_catalog
  page_file_inventory_gov --> file_header_store
  page_file_inventory_gov --> file_inventory
  page_file_inventory_gov --> file_inventory_governance
  page_file_inventory_gov --> file_summarizer
  page_file_inventory_gov --> inv_auth
  page_file_inventory_gov --> inv_email
  page_file_inventory_gov --> inv_workbench
  page_file_inventory_gov --> las_catalog
  page_file_inventory_gov --> p190_catalog
  page_file_inventory_gov --> page_file_browser
  page_file_inventory_gov --> page_shapefile_catalog
  page_file_inventory_gov --> segy_catalog
  page_file_inventory_gov --> seis_filename_parser
  page_file_manager --> audit_log
  page_file_manager --> catalog_rules
  page_file_manager --> dlis_catalog
  page_file_manager --> file_header_catalog
  page_file_manager --> file_header_store
  page_file_manager --> file_inventory
  page_file_manager --> file_inventory_governance
  page_file_manager --> file_summarizer
  page_file_manager --> inv_auth
  page_file_manager --> inv_email
  page_file_manager --> inv_workbench
  page_file_manager --> p190_catalog
  page_file_manager --> page_file_browser
  page_file_manager --> page_file_catalog
  page_file_manager --> page_workbench
  page_file_manager --> segy_catalog
  page_file_manager --> seis_filename_parser
  page_file_manager --> triage_inventory
  page_import_gom --> gom_well_loader
  page_import_gom_dir_srvy --> gom_dir_srvy_loader
  page_import_osdu --> json_well_log_catalog
  page_import_rrc --> prep_rrc_texas
  page_import_witsml --> witsml_catalog
  page_las --> db_pool
  page_las --> las_loader
  page_licence --> licence
  page_mapping_studio --> dv_table_loader
  page_mapping_studio --> fk_resolution
  page_mapping_studio --> mapping_studio
  page_monitor --> pipeline_run
  page_monitor --> promote_catalog
  page_monitor --> work_queue
  page_pipeline --> db
  page_pipeline --> db_pool
  page_pipeline --> entity_map_seed
  page_pipeline --> fk
  page_pipeline --> fk_entity
  page_pipeline --> fk_resolve_panel
  page_pipeline --> h3_grids
  page_pipeline --> mapping
  page_pipeline --> normalize
  page_pipeline --> ppdm_agent
  page_pipeline --> promote
  page_pipeline --> schema
  page_pipeline --> setup_database
  page_pipeline --> staging
  page_pipeline --> ui_helpers
  page_pipeline --> validate
  page_pipeline --> value_standardize
  page_pipeline_old --> db
  page_pipeline_old --> db_pool
  page_pipeline_old --> fk
  page_pipeline_old --> fk_entity
  page_pipeline_old --> mapping
  page_pipeline_old --> normalize
  page_pipeline_old --> ppdm_agent
  page_pipeline_old --> promote
  page_pipeline_old --> schema
  page_pipeline_old --> setup_database
  page_pipeline_old --> staging
  page_pipeline_old --> ui_helpers
  page_pipeline_old --> validate
  page_pipeline_tools (1) --> pipeline_run
  page_pipeline_tools --> pipeline_run
  page_pipeline_v3 --> db
  page_pipeline_v3 --> db_pool
  page_pipeline_v3 --> fk
  page_pipeline_v3 --> fk_entity
  page_pipeline_v3 --> mapping
  page_pipeline_v3 --> normalize
  page_pipeline_v3 --> ppdm_agent
  page_pipeline_v3 --> promote
  page_pipeline_v3 --> schema
  page_pipeline_v3 --> setup_database
  page_pipeline_v3 --> staging
  page_pipeline_v3 --> ui_helpers
  page_pipeline_v3 --> validate
  page_ppdm_map --> db_pool
  page_rules --> user_rules
  page_rules --> validate
  page_schema_overview --> schema_introspect
  page_seed --> page_bulk
  page_seed --> ui_helpers
  page_selected_documents  --> file_viewer
  page_selected_documents  --> page_well_documents
  page_selected_documents --> catalog_docs
  page_shapefile_catalog --> doc_catalog_store
  page_shapefile_catalog --> shapefile_catalog
  page_standards_manager --> ref_seeder
  page_triage --> page_workbench
  page_triage --> triage_inventory
  page_triage --> vault_copy
  page_vault --> pipeline_run
  page_well_documents (11) --> file_viewer
  page_well_documents (11) --> page_well_map
  page_well_documents --> file_viewer
  page_well_map - Copy --> boem_area_codes
  page_well_map - Copy --> boem_status_codes
  page_well_map - Copy --> dv_spatial_loader
  page_well_map - Copy --> dw_utils
  page_well_map - Copy --> petroleum_regions
  page_well_map - Copy --> state_regions
  page_well_map --> boem_area_codes
  page_well_map --> boem_geo
  page_well_map --> boem_status_codes
  page_well_map --> dv_spatial_loader
  page_well_map --> dw_utils
  page_well_map --> exporters
  page_well_map --> geography_layers
  page_well_map --> page_selected_documents
  page_well_map --> petroleum_regions
  page_well_map --> state_regions
  page_well_map --> us_geo
  page_well_map3clusters --> dv_spatial_loader
  page_well_map_baseline_2 --> dv_spatial_loader
  page_well_map_docs --> dv_spatial_loader
  page_well_map_save2 --> dv_spatial_loader
  page_well_mapa_save --> dv_spatial_loader
  page_wl_map_old --> dv_spatial_loader
  parallel_crawl --> pipeline_run
  parallel_crawl --> work_queue
  parallel_crawl --> worker_core
  path_identity --> seis_filename_parser
  pending_detail --> worker_core
  pipeline_proc_runner --> pipeline_run
  pipeline_profiler --> promote_catalog
  pipeline_run (22) --> catalog_capture
  pipeline_run (22) --> enrich_file_headers
  pipeline_run (22) --> extract_core
  pipeline_run (22) --> file_summarizer
  pipeline_run (22) --> fingerprint
  pipeline_run (22) --> page_workbench
  pipeline_run (22) --> promote_catalog
  pipeline_run (22) --> triage_inventory
  pipeline_run (22) --> vault_organizer
  pipeline_run (22) --> worker_core
  pipeline_run --> catalog_capture
  pipeline_run --> enrich_file_headers
  pipeline_run --> extract_core
  pipeline_run --> file_summarizer
  pipeline_run --> fingerprint
  pipeline_run --> page_workbench
  pipeline_run --> promote_catalog
  pipeline_run --> triage_inventory
  pipeline_run --> vault_organizer
  pipeline_run --> worker_core
  poc_geog_area --> worker_core
  poc_geog_fix --> worker_core
  poc_seis3d_geom --> worker_core
  profile_capture --> catalog_rules
  profile_capture --> pipeline_profiler
  profile_capture --> score_inventory_batch_fast
  promote_catalog --> build_catalog_mirror
  real_link_path --> worker_core
  recatalog_seis --> db_pool
  recatalog_seis --> p190_catalog
  recatalog_seis --> segy_catalog
  remaining_shp --> shapefile_catalog
  remaining_shp --> worker_core
  reset_catalog --> worker_core
  resolve_log_identity --> lis_catalog
  resolve_log_identity --> worker_core
  run_fixture_triage --> enrich_file_headers
  run_fixture_triage --> triage_inventory
  run_promote --> promote_catalog
  run_promote --> worker_core
  run_stage --> pipeline_run
  score_inventory_batch_fast --> catalog_rules
  seis_line_cols --> worker_core
  seis_when --> shapefile_catalog
  seis_when --> worker_core
  skip_detail --> worker_core
  skips --> worker_core
  slow_files --> worker_core
  test_pipeline --> catalog_rules
  test_pipeline --> db
  test_pipeline --> extract_core
  test_pipeline --> page_workbench
  test_pipeline --> pdf_survey_catalog
  test_vault_layout --> vault_copy
  time_shp_outline --> extract_core
  trace_field --> worker_core
  trace_link_gap --> worker_core
  trace_nulls --> worker_core
  trace_pipeline --> shapefile_catalog
  trace_pipeline --> worker_core
  trace_pipeline2 --> catalog_capture
  trace_pipeline2 --> worker_core
  triage_inventory --> path_identity
  uwi_errs --> worker_core
  uwi_format --> worker_core
  validate_v_well --> dw_utils
  vault_organizer --> fingerprint
  vault_run --> pipeline_run
  vault_run --> worker_core
  verify_model_a --> worker_core
  verify_seis_run --> worker_core
  whats_at --> worker_core
  why_pending --> worker_core
  worker_core --> catalog_capture
  worker_core --> dv_office_loader
  worker_core --> extract_core
  worker_core --> extract_petro
  worker_core --> json_well_log_catalog
  worker_core --> lis_catalog
  worker_core --> pdf_db_loader
  worker_core --> pdf_survey_catalog
  worker_core --> shapefile_catalog
  worker_core --> witsml_catalog
  worker_pool --> work_queue
  worker_pool --> worker_core
  classDef router fill:#f59e0b,color:#111,stroke:#333;
  classDef page fill:#38bdf8,color:#111,stroke:#333;
  classDef engine fill:#a78bfa,color:#111,stroke:#333;
  classDef module fill:#94a3b8,color:#111,stroke:#333;
```
