import { getActionHistory, getUndoableActions } from '~/server/utils/temporalAdmin'

export default defineEventHandler(() => {
  const limit = 50
  return {
    history: getActionHistory(limit),
    undoable: getUndoableActions(),
  }
})
