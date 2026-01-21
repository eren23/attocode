/**
 * Exercise Tests: Lesson 21 - Risk Assessor
 */
import { describe, it, expect } from 'vitest';
import { RiskAssessor, DEFAULT_THRESHOLDS } from './exercises/answers/exercise-1.js';

describe('RiskAssessor', () => {
  const assessor = new RiskAssessor(DEFAULT_THRESHOLDS);

  it('should assess low risk for file read', () => {
    const result = assessor.assess({ type: 'file_read', target: '/tmp/file.txt' });
    expect(result.level).toBe('none');
    expect(result.recommendation).toBe('auto_approve');
  });

  it('should assess medium risk for non-recursive delete', () => {
    const result = assessor.assess({ type: 'file_delete', target: '/tmp/file.txt' });
    expect(result.level).toBe('medium');
    expect(result.recommendation).toBe('require_approval');
  });

  it('should assess high risk for recursive delete', () => {
    const result = assessor.assess({ type: 'file_delete', target: '/tmp', recursive: true });
    expect(result.level).toBe('high');
    expect(result.factors).toContain('recursive_delete');
  });

  it('should assess critical risk for production deployment', () => {
    const result = assessor.assess({ type: 'deployment', target: 'app', environment: 'production' });
    expect(result.level).toBe('critical');
    expect(result.recommendation).toBe('block');
  });

  it('should convert scores to levels correctly', () => {
    expect(assessor.getLevel(5)).toBe('none');
    expect(assessor.getLevel(20)).toBe('low');
    expect(assessor.getLevel(40)).toBe('medium');
    expect(assessor.getLevel(60)).toBe('high');
    expect(assessor.getLevel(90)).toBe('critical');
  });
});
