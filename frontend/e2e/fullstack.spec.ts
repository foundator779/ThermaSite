import { expect, test, type Page } from '@playwright/test'

const now = '2026-08-25T12:00:00Z'
const screeningId = '00000000-0000-4000-8000-000000000026'

const sites = [
  { id: 'phoenix-az', name: 'Buckeye West Valley Industrial Edge', metro: 'Buckeye', state: 'AZ', latitude: 33.4435, longitude: -112.587, industrial_energy_price_cents_kwh: 7.9, water_risk_0_5: 4.5, permitting_score: 72, logistics_score: 90, permitting_status: 'administrative review' },
  { id: 'columbus-oh', name: 'New Albany International Business Park Edge', metro: 'New Albany', state: 'OH', latitude: 40.112, longitude: -82.749, industrial_energy_price_cents_kwh: 7.1, water_risk_0_5: 1.4, permitting_score: 82, logistics_score: 88, permitting_status: 'documented development review' },
  { id: 'hillsboro-or', name: 'North Hillsboro Industrial Edge', metro: 'Hillsboro', state: 'OR', latitude: 45.57, longitude: -122.968, industrial_energy_price_cents_kwh: 8.05, water_risk_0_5: 1.8, permitting_score: 78, logistics_score: 94, permitting_status: 'established industrial review' },
  { id: 'council-bluffs-ia', name: 'South Council Bluffs Industrial Edge', metro: 'Council Bluffs', state: 'IA', latitude: 41.198, longitude: -95.789, industrial_energy_price_cents_kwh: 7.2, water_risk_0_5: 1.3, permitting_score: 84, logistics_score: 92, permitting_status: 'documented development review' },
  { id: 'ashburn-va', name: 'Loudoun Route 606 Industrial Edge', metro: 'Loudoun Gateway', state: 'VA', latitude: 38.958, longitude: -77.5115, industrial_energy_price_cents_kwh: 9, water_risk_0_5: 1.8, permitting_score: 70, logistics_score: 98, permitting_status: 'discretionary multi-agency review' },
].map((site, index) => ({
  ...site, area_sq_mi: 1, catalog: true, warnings: [], research_summary: 'Official-source screening evidence cached for the preset demo.',
  shortlist_reason: 'Selected from sourced national evidence before the final FortyGuard rank.',
  citations: [{ title: 'Official market evidence', url: `https://example.com/source-${index}`, publisher: 'Official source', retrieved_at: now, fact: 'Attributed screening fact.', official: true }],
  thermal: { activity_ids: [`activity-${index}`], mean_temperature_c: [36, 27, 24, 26, 29][index], maximum_temperature_c: [47, 38, 34, 36, 39][index], exceedance_ratio: [.68, .16, .05, .1, .2][index], threshold_c: 35, source: 'FortyGuard Temperature API', map_data: { type: 'FeatureCollection', features: [] } },
}))

function recommendation(siteId: string, rank: number, score: number) {
  return {
    site_id: siteId, rank, score, decision_readiness: .82, rankable: true, eligible: true,
    constraint_failures: [], cooling_burden_index: 100 - score,
    selected_window_cooling_cost_usd: 510000 + rank * 13000,
    factor_scores: ['thermal', 'power', 'water', 'permitting', 'logistics'].map((factor, index) => ({
      factor, score: Math.max(35, score - index * 3), confidence: index ? .75 : 1,
      weight: [.4, .25, .15, .1, .1][index], contribution: 15, detail: `Cited ${factor} evidence.`,
    })),
  }
}

const baseRequest = {
  brief: 'Find five industrial-edge search zones for a 50 MW data-center investment.',
  candidate_ids: [], candidates: [], auto_shortlist: true,
  facility: { facility_size_acres: 40, it_density_mw_per_acre: 1.25, cooling_system: 'hybrid', shortlist_size: 5 },
  weights: { thermal: 40, power: 25, water: 15, permitting: 10, logistics: 10 },
  constraints: { exclude_permitting_moratoria: true },
  cooling: { it_load_mw: 50, utilization: .85, baseline_pue: 1.2, reference_temperature_c: 18, pue_sensitivity_per_c: .006, annualize: false },
  thermal_window: { start_date: '2026-07-01', end_date: '2026-07-31', threshold_c: 35, granularity_m: 100 },
}

function automaticEstimate(siteId: string, index: number) {
  const site = sites[index]
  const delta = .002
  const ring = [[site.longitude - delta, site.latitude - delta], [site.longitude + delta, site.latitude - delta], [site.longitude + delta, site.latitude + delta], [site.longitude - delta, site.latitude + delta], [site.longitude - delta, site.latitude - delta]]
  return {
    id: `00000000-0000-4000-8000-00000000020${index}`, site_id: siteId, created_at: now,
    polygon: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { purpose: 'planned_facility' }, geometry: { type: 'Polygon', coordinates: [ring] } }] },
    area_acres: 40, area_sq_mi: .0625, cooling_system: 'hybrid', it_density_mw_per_acre: 1.25,
    it_load_mw: 50, utilization: .85, baseline_pue: 1.2, heat_adjusted_pue: 1.24 + index * .01, peak_pue: 1.31,
    average_facility_power_mw: 52.7 + index, peak_facility_power_mw: 62 + index,
    window_it_energy_mwh: 31620, window_facility_energy_mwh: 39228,
    window_water_liters_low: 10770000, window_water_liters_high: 43080000,
    window_water_gallons_low: 2845123, window_water_gallons_high: 11380492,
    illustrative_annual_energy_mwh: 461678, illustrative_annual_water_gallons_low: 33490000,
    illustrative_annual_water_gallons_high: 133960000, wue_l_kwh_low: .341, wue_l_kwh_high: 1.362,
    thermal: site.thermal, confidence: .72, assumptions: ['Planning capacity derives from acreage and design density.'], disclaimer: 'Scenario estimate only.',
  }
}

function completedRecord() {
  const strategies = [
    ['Current investment lens', 'User-selected priorities', 'hillsboro-or', 84.2, 1.8],
    ['Thermal resilience', 'Heat and cooling continuity', 'hillsboro-or', 88.1, 3.2],
    ['Power economics', 'Industrial electricity exposure', 'columbus-oh', 83.4, 1.1],
    ['Water constrained', 'Local water-risk sensitivity', 'hillsboro-or', 86.7, 2.4],
    ['Delivery speed', 'Permitting and infrastructure readiness', 'hillsboro-or', 85.3, 1.5],
  ].map(([name, emphasis, winner_site_id, winner_score, margin_to_second]) => ({
    name, emphasis, winner_site_id, winner_score, margin_to_second,
    weights: structuredClone(baseRequest.weights),
  }))
  return {
    id: screeningId, status: 'COMPLETED', created_at: now, updated_at: now,
    request: structuredClone(baseRequest), candidates: structuredClone(sites), resource_estimates: sites.map((site, index) => automaticEstimate(site.id, index)),
    recommendations: [recommendation('hillsboro-or', 1, 84.2), recommendation('council-bluffs-ia', 2, 82.4), recommendation('columbus-oh', 3, 79.8), recommendation('ashburn-va', 4, 74.3), recommendation('phoenix-az', 5, 61.4)],
    decision_analysis: {
      leader_site_id: 'hillsboro-or', hottest_site_id: 'phoenix-az', costliest_site_id: 'ashburn-va', window_days: 31,
      leader_window_energy_cost_usd: 3150000, costliest_window_energy_cost_usd: 3560000, window_cost_advantage_usd: 410000,
      window_energy_avoided_mwh: 3040, window_water_avoided_gallons_low: 520000, window_water_avoided_gallons_high: 2080000,
      robustness_wins: 4, robustness_total: 5, robustness_label: 'resilient', strategies,
      assumptions: ['Selected-window comparisons use the same facility profile.'],
    },
    events: [
      { id: '00000000-0000-4000-8000-000000000001', timestamp: now, agent: 'Heat Agent', type: 'fortyguard.analysis.completed', message: 'FortyGuard returned matched thermal evidence.', status: 'success', payload: {} },
      { id: '00000000-0000-4000-8000-000000000002', timestamp: now, agent: 'Evidence Audit Gate', type: 'screening.audit.completed', message: 'Every ranked site has thermal and non-thermal provenance.', status: 'success', payload: {} },
    ],
    progress: 100, current_step: 'complete', summary: 'North Hillsboro Industrial Edge leads this screening at 84.2/100 with 82% decision readiness.',
    due_diligence: ['Obtain a utility load letter.', 'Confirm zoning and review timing.', 'Secure local water-provider capacity documentation.'],
    artifacts: [{ id: '00000000-0000-4000-8000-000000000101', name: 'thermasite_investment_memo.md', content_type: 'text/markdown', size_bytes: 4200 }],
    audit: { passed: true, warnings: [], summary: 'Evidence audit passed; every ranked site has thermal and non-thermal provenance.' },
  }
}

async function mockThermaSite(page: Page) {
  const record = completedRecord()
  const demoUser = { id: '00000000-0000-4000-8000-000000000777', email: 'judge@thermasite.demo', name: 'Hackathon Judge', is_demo: true }
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/demo')) return route.fulfill({ json: { token: 'judge-session-token', user: demoUser } })
    if (path.endsWith('/auth/me')) return route.fulfill({ json: demoUser })
    if (path.endsWith('/auth/logout')) return route.fulfill({ status: 204, body: '' })
    if (path.endsWith('/readyz')) return route.fulfill({ json: { status: 'ready', environment: 'test', checks: { gemini: { configured: true, model: 'gemini-test', provider: 'Gemini', sdk: 'GenAI', agent_framework: 'ADK' }, fortyguard: { configured: true, provider: 'FortyGuard', authentication: 'backend', aoi_limit_sq_mi: 10 }, grounded_research: { configured: true, provider: 'Gemini', cache_ttl_days: 7 }, persistence: 'local', artifact_storage: 'local' } } })
    if (path.endsWith('/site-catalog')) return route.fulfill({ json: { version: '2026.08.3', sites } })
    if (path.endsWith('/screenings') && request.method() === 'POST') return route.fulfill({ status: 202, json: { screening_id: screeningId, status: 'CREATED' } })
    if (path.endsWith(`/screenings/${screeningId}/events`)) return route.fulfill({ contentType: 'text/event-stream', body: '' })
    if (path.endsWith(`/screenings/${screeningId}/rescore`)) {
      const body = request.postDataJSON()
      record.request.weights = body.weights
      record.recommendations = [recommendation('phoenix-az', 1, 86.1), recommendation('columbus-oh', 2, 78.2), recommendation('hillsboro-or', 3, 73.5), recommendation('council-bluffs-ia', 4, 71.2), recommendation('ashburn-va', 5, 69.8)]
      record.decision_analysis.leader_site_id = 'phoenix-az'
      record.decision_analysis.robustness_wins = 3
      record.decision_analysis.robustness_label = 'competitive'
      record.summary = 'Buckeye West Valley Industrial Edge leads after the updated investment weights.'
      return route.fulfill({ json: record })
    }
    if (path.endsWith(`/screenings/${screeningId}/estimate`)) {
      const body = request.postDataJSON()
      const estimate = {
        id: '00000000-0000-4000-8000-000000000202', site_id: body.site_id, created_at: now,
        polygon: body.polygon, area_acres: 40, area_sq_mi: .0625, cooling_system: body.cooling_system,
        it_load_mw: body.it_load_mw, utilization: body.utilization, baseline_pue: body.baseline_pue,
        heat_adjusted_pue: 1.308, peak_pue: 1.374,
        average_facility_power_mw: 55.59, peak_facility_power_mw: 68.7,
        window_it_energy_mwh: 31620, window_facility_energy_mwh: 41358.96,
        window_water_liters_low: 12500000, window_water_liters_high: 50000000,
        window_water_gallons_low: 3302150, window_water_gallons_high: 13208602,
        illustrative_annual_energy_mwh: 487054, illustrative_annual_water_gallons_low: 38880000,
        illustrative_annual_water_gallons_high: 155520000, wue_l_kwh_low: .396, wue_l_kwh_high: 1.584,
        thermal: sites[0].thermal, confidence: .72,
        assumptions: ['50 MW nameplate IT load at 85% utilization.', 'Annual figures extrapolate the selected heat window and are illustrative.'],
        disclaimer: 'Scenario estimate only; not an engineering design or utility commitment.',
      }
      record.resource_estimates = [estimate]
      return route.fulfill({ json: estimate })
    }
    if (path.endsWith(`/screenings/${screeningId}`)) return route.fulfill({ json: record })
    if (path.endsWith('/screenings')) return route.fulfill({ json: [record] })
    return route.fulfill({ status: 404, json: { detail: 'not mocked' } })
  })
}

async function enterJudgeDemo(page: Page) {
  await expect(page.getByRole('heading', { name: 'Welcome back.' })).toBeVisible()
  await page.getByRole('button', { name: /Enter judge demo/ }).click()
  await expect(page.getByRole('heading', { name: /Describe the facility/ })).toBeVisible()
}

test.describe('ThermaSite mocked acceptance journey', () => {
  test('launches, ranks, rescales, cites, and reopens the preset screening', async ({ page }) => {
    await mockThermaSite(page)
    await page.goto('/')

    await expect(page).toHaveTitle('ThermaSite — Where should the next megawatt live?')
    await expect(page.getByRole('heading', { name: /Decisions this large/ })).toBeVisible()
    await enterJudgeDemo(page)
    await expect(page.getByRole('heading', { name: /Describe the facility/ })).toBeVisible()
    await page.getByLabel('Campus size, acres').fill('60')
    await expect(page.getByText('75.0 MW IT')).toBeVisible()
    expect(await page.locator('body').evaluate((node) => getComputedStyle(node).fontFamily)).toContain('Inter Variable')

    await page.getByRole('button', { name: /Find my top five locations/ }).click()
    await expect(page.getByRole('heading', { name: 'Hillsboro fits best.' })).toBeVisible()
    await expect(page.locator('.rank-card')).toHaveCount(5)
    await expect(page.locator('.result-card')).toHaveCount(5)
    await expect(page.locator('.agent-trace')).toContainText('FortyGuard returned matched thermal evidence.')
    await expect(page.locator('.map-caption')).toContainText('industrial-edge search zone')
    await expect(page.locator('.map-caption')).toContainText('not parcel availability')
    await expect(page.locator('.impact-section')).toContainText('Average facility power')
    await expect(page.locator('.impact-section')).toContainText('MW')
    await expect(page.locator('.impact-section')).toContainText('July direct water')
    await expect(page.locator('.decision-case')).toContainText('4/5')
    await expect(page.locator('.decision-case')).toContainText('July cost advantage')
    await expect(page.locator('.strategy-row')).toHaveCount(6)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Hillsboro fits best.' })).toBeVisible()
    await expect(page.locator('.impact-section')).toContainText('Average facility power')

    await page.getByRole('button', { name: /Evidence & memo/ }).click()
    const drawer = page.getByRole('dialog', { name: 'Evidence & exports' })
    await expect(drawer).toContainText('Audit passed')
    await expect(drawer.getByRole('link')).toHaveCount(5)
    await expect(drawer.getByRole('button', { name: /thermasite_investment_memo/ })).toBeVisible()
    await drawer.getByRole('button', { name: 'Close evidence' }).click()

    await page.locator('.weight-editor input').first().fill('65')
    await page.getByRole('button', { name: /Apply weights/ }).click()
    await expect(page.getByRole('heading', { name: 'Buckeye fits best.' })).toBeVisible()
    await expect(page.locator('.result-card').first()).toContainText('Buckeye')

    await page.getByRole('button', { name: 'Decisions' }).click()
    await expect(page.getByRole('heading', { name: 'Previous screenings.' })).toBeVisible()
    await page.locator('.history-list > button').click()
    await expect(page.getByRole('heading', { name: 'Buckeye fits best.' })).toBeVisible()
  })

  test('keeps navigation usable on mobile and honors reduced motion', async ({ page }) => {
    await mockThermaSite(page)
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    await enterJudgeDemo(page)
    await page.getByRole('button', { name: 'Toggle navigation' }).click()
    await expect(page.getByRole('button', { name: 'Decisions' })).toBeVisible()
    expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(true)
    expect(await page.locator('.primary-action').evaluate((node) => getComputedStyle(node).transitionDuration)).not.toBe('0.18s')
  })

  test('renders an actionable FortyGuard failure state', async ({ page }) => {
    await mockThermaSite(page)
    await page.route('**/api/v1/screenings', async (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ status: 429, json: { detail: 'FortyGuard rate limit was reached; retry after the provider window resets.' } })
      }
      return route.fallback()
    })
    await page.goto('/')
    await enterJudgeDemo(page)
    await page.getByRole('button', { name: /Find my top five locations/ }).click()
    await expect(page.locator('.inline-error')).toContainText('FortyGuard rate limit')
    await expect(page.getByRole('button', { name: /Find my top five locations/ })).toBeEnabled()
  })
})

test.describe('ThermaSite live provider smoke', () => {
  test.skip(!process.env.E2E_LIVE_RESEARCH, 'Set E2E_LIVE_RESEARCH=1 to use live FortyGuard and Gemini calls.')

  test('@live accepts one real FortyGuard-backed preset screening', async ({ page }) => {
    test.setTimeout(720_000)
    await page.goto('/')
    await expect(page.locator('.header-status')).toContainText('FortyGuard ready')
    await page.getByRole('button', { name: /Find my top five locations/ }).click()
    await expect(page.getByText(/ThermaSite completed|leads this screening/).first()).toBeVisible({ timeout: 700_000 })
  })
})
