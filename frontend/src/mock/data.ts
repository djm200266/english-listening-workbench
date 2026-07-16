/**
 * Backward-compatible re-exports from repository.ts.
 * New code should import from '../mock/repository' or use '../services/api'.
 */

export {
  listMockTasks as mockTasks,
  getMockTask as mockGetTask,
  createMockTask as mockCreateTask,
  updateMockTask as mockUpdateTask,
  deleteMockTask as mockDeleteTask,
} from './repository';
