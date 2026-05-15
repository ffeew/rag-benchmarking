# Eval cases verification report

Source: `backend/eval_cases/sec_filings_v1.yaml`

- Cases: **99**
- Passed: **99**
- Failed: **0**

## All cases

| Status | Case key | Category | Notes |
| --- | --- | --- | --- |
| PASS | `aapl_2025_total_net_sales_millions` | single_company_lookup |  |
| PASS | `msft_2025_intelligent_cloud_revenue_millions` | single_company_lookup |  |
| PASS | `nvda_2026_data_center_revenue_millions` | single_company_lookup |  |
| PASS | `meta_2025_family_daily_active_people` | single_company_lookup |  |
| PASS | `jpm_2025_total_net_revenue_millions` | single_company_lookup |  |
| PASS | `aapl_2025_iphone_net_sales_millions` | table_lookup |  |
| PASS | `aapl_2025_cash_equivalents_millions` | table_lookup |  |
| PASS | `msft_2025_rd_expense_millions` | table_lookup |  |
| PASS | `amzn_2025_aws_operating_income_millions` | table_lookup |  |
| PASS | `tsla_2025_energy_revenue_millions` | table_lookup |  |
| PASS | `jpm_2025_cet1_standardized_percent` | table_lookup |  |
| PASS | `aapl_iphone_net_sales_yoy_percent` | trend |  |
| PASS | `nvda_data_center_revenue_yoy_percent` | trend |  |
| PASS | `amzn_aws_sales_yoy_percent` | trend |  |
| PASS | `meta_advertising_revenue_yoy_percent` | trend |  |
| PASS | `tsla_total_revenue_decrease_percent` | trend |  |
| PASS | `aapl_vs_msft_2025_total_revenue` | cross_company_comparison |  |
| PASS | `nvda_vs_meta_2025_total_revenue` | cross_company_comparison | synthesized: value_text 'NVIDIA' for label='higher_company' not found on any cited page or filename |
| PASS | `amzn_vs_tsla_2025_total_revenue` | cross_company_comparison |  |
| PASS | `aapl_2025_iphone_and_services_sales` | multi_part |  |
| PASS | `amzn_2025_segment_sales` | multi_part |  |
| PASS | `meta_2025_segment_revenue` | multi_part |  |
| PASS | `latest_aapl_10k_filing_date_and_sales` | latest_filing |  |
| PASS | `latest_nvda_10k_filing_date_and_data_center` | latest_filing |  |
| PASS | `highest_revenue_large_tech_subset` | sector_synthesis |  |
| PASS | `aapl_2027_total_net_sales_insufficient` | insufficient_evidence |  |
| PASS | `msft_2028_azure_revenue_insufficient` | insufficient_evidence |  |
| PASS | `jpm_apple_card_purchase_price_insufficient` | insufficient_evidence |  |
| PASS | `nvda_buy_stock_refusal` | refusal |  |
| PASS | `msft_2025_total_revenue_millions` | single_company_lookup |  |
| PASS | `goog_2025_total_revenue_millions` | single_company_lookup |  |
| PASS | `aapl_2025_long_term_debt_millions` | single_company_lookup |  |
| PASS | `amd_2025_data_center_revenue_billions` | single_company_lookup |  |
| PASS | `bac_2025_total_revenue_millions` | single_company_lookup |  |
| PASS | `aapl_2025_americas_net_sales_millions` | table_lookup |  |
| PASS | `aapl_2025_greater_china_net_sales_millions` | table_lookup |  |
| PASS | `msft_2025_gross_margin_millions` | table_lookup |  |
| PASS | `goog_2025_google_cloud_revenue_millions` | table_lookup |  |
| PASS | `aapl_total_gross_margin_pct_3yr_trend` | trend |  |
| PASS | `msft_total_revenue_3yr_trend_millions` | trend |  |
| PASS | `goog_total_revenue_3yr_trend_millions` | trend |  |
| PASS | `goog_vs_msft_rd_pct_of_revenue_2025` | cross_company_comparison | synthesized: value_numeric 15.16 (unit=percent) for label='goog_rd_pct' not found on any cited page |
| PASS | `aapl_vs_msft_gross_margin_pct_2025` | cross_company_comparison | synthesized: value_numeric 68.8 (unit=percent) for label='msft_gross_margin_pct' not found on any cited page; synthesized: value_text 'Microsoft' for label='higher_company' not found on any cited page or filename |
| PASS | `nvda_vs_amd_data_center_revenue_2025` | cross_company_comparison |  |
| PASS | `bac_vs_jpm_total_revenue_2025` | cross_company_comparison |  |
| PASS | `cloud_segment_revenue_ranking_2025` | cross_company_comparison |  |
| PASS | `msft_total_revenue_and_gross_margin_2025` | multi_part |  |
| PASS | `amd_total_and_data_center_revenue_2025` | multi_part |  |
| PASS | `goog_revenue_and_capex_2025` | multi_part |  |
| PASS | `latest_msft_10q_filing_date` | latest_filing |  |
| PASS | `latest_aapl_8k_filing_date` | latest_filing |  |
| PASS | `latest_nvda_8k_filing_date` | latest_filing |  |
| PASS | `openai_2025_revenue_insufficient` | insufficient_evidence |  |
| PASS | `goog_q1_fy2026_revenue_insufficient` | insufficient_evidence |  |
| PASS | `tech_megacap_rd_spend_ranking_2025` | sector_synthesis |  |
| PASS | `tech_megacap_net_income_ranking_2025` | sector_synthesis |  |
| PASS | `semiconductor_data_center_ai_demand_2025` | sector_synthesis |  |
| PASS | `us_megabanks_2025_revenue_ranking` | sector_synthesis |  |
| PASS | `hyperscaler_2025_capex_alphabet` | sector_synthesis |  |
| PASS | `aapl_buy_stock_refusal` | refusal |  |
| PASS | `portfolio_allocation_refusal` | refusal |  |
| PASS | `nvda_price_target_refusal` | refusal |  |
| PASS | `ma_speculation_refusal` | refusal |  |
| PASS | `msft_q2_fy2026_total_revenue_millions` | single_company_lookup |  |
| PASS | `aapl_q1_fy2026_iphone_net_sales_millions` | single_company_lookup |  |
| PASS | `nvda_q3_fy2026_data_center_revenue_millions` | single_company_lookup |  |
| PASS | `jpm_q3_2025_net_interest_income_millions` | single_company_lookup |  |
| PASS | `tsla_q3_2025_total_revenues_millions` | single_company_lookup |  |
| PASS | `amzn_q3_2025_aws_net_sales_millions` | single_company_lookup |  |
| PASS | `aapl_8k_2026_01_29_quarter_period` | latest_filing |  |
| PASS | `nvda_8k_2026_02_25_press_release_title` | latest_filing |  |
| PASS | `tsla_8k_2026_01_28_reporting_period` | latest_filing |  |
| PASS | `pm_8k_2026_03_13_segment_realignment` | single_company_lookup |  |
| PASS | `lly_2025_revenue_millions` | single_company_lookup |  |
| PASS | `mrk_2025_total_sales_millions` | single_company_lookup |  |
| PASS | `jnj_2025_sales_to_customers_millions` | single_company_lookup |  |
| PASS | `unh_2025_total_revenues_millions` | single_company_lookup |  |
| PASS | `xom_2025_sales_other_operating_revenue_millions` | single_company_lookup |  |
| PASS | `cvx_2025_sales_other_operating_revenues_millions` | single_company_lookup |  |
| PASS | `wmt_fy2026_net_sales_millions` | single_company_lookup |  |
| PASS | `cost_fy2025_net_sales_millions` | single_company_lookup |  |
| PASS | `ko_2025_net_operating_revenues_millions` | single_company_lookup |  |
| PASS | `t_2025_total_operating_revenues_millions` | single_company_lookup |  |
| PASS | `vz_2025_total_operating_revenues_millions` | single_company_lookup |  |
| PASS | `gs_2025_total_net_revenues_millions` | single_company_lookup |  |
| PASS | `cat_2025_sales_and_revenues_millions` | single_company_lookup |  |
| PASS | `avgo_fy2025_total_net_revenue_millions` | single_company_lookup |  |
| PASS | `intc_2025_total_net_revenue_millions` | single_company_lookup |  |
| PASS | `cross_sector_2025_revenue_ranking` | sector_synthesis |  |
| PASS | `aapl_2025_supply_chain_risk_factor` | single_company_lookup |  |
| PASS | `nvda_2026_h20_export_charge_billions` | single_company_lookup |  |
| PASS | `meta_2025_advertising_revenue_drivers` | multi_part |  |
| PASS | `msft_2025_ai_infrastructure_cost_commentary` | single_company_lookup |  |
| PASS | `aapl_q1_fy2026_vs_fy2025_total_net_sales` | multi_part |  |
| PASS | `nvda_fy25_vs_fy26_revenue_in_fy26_10k` | multi_part |  |
| PASS | `meta_2025_diluted_eps_and_capex` | multi_part |  |
| PASS | `tsla_2025_regulatory_credits_revenue_millions` | table_lookup |  |
| PASS | `mcd_2025_10k_total_revenue_insufficient` | insufficient_evidence |  |
| PASS | `nflx_q1_2025_revenue_insufficient` | insufficient_evidence |  |
