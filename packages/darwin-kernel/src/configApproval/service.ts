import type { ConfigRequest, ConfigApproval, ConfigRequestStatus } from './types.ts';

export interface ConfigApprovalPorts {
  insertRequest(req: Omit<ConfigRequest, 'id' | 'created_at'>): Promise<ConfigRequest>;
  fetchPendingRequests(): Promise<ConfigRequest[]>;
  fetchRequestsByRequester(requester: string): Promise<ConfigRequest[]>;
  updateRequestStatus(requestId: string, status: ConfigRequestStatus): Promise<void>;
  insertApproval(approval: Omit<ConfigApproval, 'id' | 'decided_at'>): Promise<ConfigApproval>;
  fetchApprovals(requestId: string): Promise<ConfigApproval[]>;
}

export async function createConfigRequest(
  ports: ConfigApprovalPorts,
  key: string,
  value: string,
  requester: string,
): Promise<ConfigRequest> {
  return ports.insertRequest({ key, value, requester, status: 'pending' });
}

export async function getPendingConfigRequests(ports: ConfigApprovalPorts): Promise<ConfigRequest[]> {
  return ports.fetchPendingRequests();
}

export async function getRequestsByRequester(
  ports: ConfigApprovalPorts,
  requester: string,
): Promise<ConfigRequest[]> {
  return ports.fetchRequestsByRequester(requester);
}

export async function approveConfigRequest(
  ports: ConfigApprovalPorts,
  requestId: string,
  approverId: string,
  reason: string,
): Promise<ConfigApproval> {
  await ports.updateRequestStatus(requestId, 'approved');
  return ports.insertApproval({ request_id: requestId, approver: approverId, decision: 'approved', reason });
}

export async function rejectConfigRequest(
  ports: ConfigApprovalPorts,
  requestId: string,
  approverId: string,
  reason: string,
): Promise<ConfigApproval> {
  await ports.updateRequestStatus(requestId, 'rejected');
  return ports.insertApproval({ request_id: requestId, approver: approverId, decision: 'rejected', reason });
}

export async function getApprovalDetails(
  ports: ConfigApprovalPorts,
  requestId: string,
): Promise<ConfigApproval[]> {
  return ports.fetchApprovals(requestId);
}
