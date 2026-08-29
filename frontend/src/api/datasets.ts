import { api } from './client'
import type { DatasetRegistry } from '../types/run'

export async function listDatasets() {
  return api<DatasetRegistry>('/api/v1/datasets')
}
