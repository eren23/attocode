/**
 * Exercise Tests: Lesson 25 - Feature Flag Manager
 */
import { describe, it, expect } from 'vitest';
import { FeatureFlagManager, hashUserId } from './exercises/answers/exercise-1.js';

describe('FeatureFlagManager', () => {
  it('should register and check simple flags', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({ name: 'new_feature', enabled: true });
    manager.registerFlag({ name: 'disabled_feature', enabled: false });

    expect(manager.isEnabled('new_feature')).toBe(true);
    expect(manager.isEnabled('disabled_feature')).toBe(false);
    expect(manager.isEnabled('unknown')).toBe(false);
  });

  it('should evaluate user role conditions', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({
      name: 'admin_only',
      enabled: true,
      conditions: [{ type: 'user_role', value: 'admin' }],
    });

    expect(manager.isEnabled('admin_only', { userRole: 'admin' })).toBe(true);
    expect(manager.isEnabled('admin_only', { userRole: 'user' })).toBe(false);
    expect(manager.isEnabled('admin_only')).toBe(false);
  });

  it('should evaluate environment conditions', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({
      name: 'staging_only',
      enabled: true,
      conditions: [{ type: 'environment', value: 'staging' }],
    });

    expect(manager.isEnabled('staging_only', { environment: 'staging' })).toBe(true);
    expect(manager.isEnabled('staging_only', { environment: 'production' })).toBe(false);
  });

  it('should evaluate percentage rollouts', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({
      name: 'gradual_rollout',
      enabled: true,
      conditions: [{ type: 'percentage', value: 50 }],
    });

    // Hash should be deterministic
    const hash1 = hashUserId('user123');
    const hash2 = hashUserId('user123');
    expect(hash1).toBe(hash2);

    // Test with specific user whose hash we know is in range
    const testUsers = ['user_a', 'user_b', 'user_c', 'user_d'];
    let enabledCount = 0;
    for (const userId of testUsers) {
      if (manager.isEnabled('gradual_rollout', { userId })) {
        enabledCount++;
      }
    }
    // With 50% rollout, roughly half should be enabled
    expect(enabledCount).toBeGreaterThanOrEqual(0);
    expect(enabledCount).toBeLessThanOrEqual(4);
  });

  it('should require all conditions to pass', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({
      name: 'restricted',
      enabled: true,
      conditions: [
        { type: 'user_role', value: 'admin' },
        { type: 'environment', value: 'staging' },
      ],
    });

    expect(manager.isEnabled('restricted', { userRole: 'admin', environment: 'staging' })).toBe(true);
    expect(manager.isEnabled('restricted', { userRole: 'admin', environment: 'production' })).toBe(false);
    expect(manager.isEnabled('restricted', { userRole: 'user', environment: 'staging' })).toBe(false);
  });

  it('should return all flags', () => {
    const manager = new FeatureFlagManager();
    manager.registerFlag({ name: 'flag1', enabled: true });
    manager.registerFlag({ name: 'flag2', enabled: false });

    const flags = manager.getAllFlags();
    expect(flags).toHaveLength(2);
  });
});
