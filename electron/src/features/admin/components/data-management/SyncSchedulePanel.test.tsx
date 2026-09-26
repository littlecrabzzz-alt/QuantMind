import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { adminService } from '../../services/adminService';
import { SyncSchedulePanel } from './SyncSchedulePanel';

vi.mock('../../services/adminService', () => ({
    adminService: {
        getSyncSchedule: vi.fn(),
        saveSyncSchedule: vi.fn(),
    },
}));

beforeEach(() => vi.clearAllMocks());

it.each([['BC', true], ['HK', false]] as const)(
    'preserves %s research preparation when saving other schedule fields',
    async (market, withQlib) => {
        vi.mocked(adminService.getSyncSchedule).mockResolvedValue({
            data: { enabled: false, time: '08:15', days: 30, datasets: ['daily_forward'], with_qlib: withQlib },
        });
        render(<SyncSchedulePanel market={market} />);
        const save = screen.getByRole('button', { name: '保存定时配置' });
        await waitFor(() => expect(save).not.toBeDisabled());
        fireEvent.click(save);
        await waitFor(() => expect(adminService.saveSyncSchedule).toHaveBeenCalledWith(
            market,
            expect.objectContaining({ days: 30, datasets: ['daily_forward'], with_qlib: withQlib }),
        ));
    },
);
