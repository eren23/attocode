#!/usr/bin/env tsx
/**
 * Exercise Verification Script
 *
 * Verifies that:
 * 1. All exercise files exist
 * 2. All answer files exist
 * 3. Exercise tests pass with answer implementations
 * 4. Exercise templates have TODO markers
 *
 * Run: npx tsx testing/verify-exercises.ts
 */

import { existsSync, readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import { spawnSync } from 'child_process';

const ROOT_DIR = process.cwd();
const LESSONS = Array.from({ length: 26 }, (_, i) => i + 1);

interface VerificationResult {
  lesson: number;
  exerciseExists: boolean;
  answersExist: boolean;
  hasTodos: boolean;
  testsPass: boolean | null;
  errors: string[];
}

function getLessonDir(lesson: number): string {
  const prefix = lesson.toString().padStart(2, '0');
  const dirs = readdirSync(ROOT_DIR).filter(d => d.startsWith(prefix + '-'));
  return dirs[0] || '';
}

function verifyLesson(lesson: number): VerificationResult {
  const result: VerificationResult = {
    lesson,
    exerciseExists: false,
    answersExist: false,
    hasTodos: false,
    testsPass: null,
    errors: [],
  };

  const lessonDir = getLessonDir(lesson);
  if (!lessonDir) {
    result.errors.push(`Lesson directory not found for lesson ${lesson}`);
    return result;
  }

  const exercisesDir = join(ROOT_DIR, lessonDir, 'exercises');
  const answersDir = join(exercisesDir, 'answers');
  const exerciseTestFile = join(ROOT_DIR, lessonDir, 'exercises.test.ts');

  // Check if exercises directory exists
  if (existsSync(exercisesDir)) {
    result.exerciseExists = true;

    // Check for exercise files
    const exerciseFiles = readdirSync(exercisesDir).filter(
      f => f.endsWith('.ts') && !f.includes('.test.')
    );

    if (exerciseFiles.length === 0) {
      result.errors.push('No exercise files found');
    }

    // Check for TODO markers in exercise files
    for (const file of exerciseFiles) {
      if (file === 'README.md') continue;
      const content = readFileSync(join(exercisesDir, file), 'utf-8');
      if (content.includes('TODO') || content.includes('IMPLEMENT')) {
        result.hasTodos = true;
      }
    }

    if (!result.hasTodos && exerciseFiles.length > 0) {
      result.errors.push('Exercise files missing TODO markers');
    }
  } else {
    result.errors.push('Exercises directory not found');
  }

  // Check if answers directory exists
  if (existsSync(answersDir)) {
    result.answersExist = true;

    const answerFiles = readdirSync(answersDir).filter(f => f.endsWith('.ts'));
    if (answerFiles.length === 0) {
      result.errors.push('No answer files found');
    }
  } else {
    result.errors.push('Answers directory not found');
  }

  // Check if test file exists and passes
  // Using spawnSync with explicit args to avoid shell injection
  if (existsSync(exerciseTestFile)) {
    const vitestResult = spawnSync('npx', ['vitest', 'run', exerciseTestFile, '--reporter=silent'], {
      cwd: ROOT_DIR,
      stdio: 'pipe',
    });
    result.testsPass = vitestResult.status === 0;
    if (!result.testsPass) {
      result.errors.push('Exercise tests failed');
    }
  } else {
    result.errors.push('Exercise test file not found');
  }

  return result;
}

function printResults(results: VerificationResult[]): void {
  console.log('\n📋 Exercise Verification Report\n');
  console.log('═'.repeat(70));

  let totalExercises = 0;
  let totalPassing = 0;
  let totalMissing = 0;

  for (const result of results) {
    const status = result.exerciseExists && result.answersExist && result.testsPass
      ? '✅'
      : result.exerciseExists
        ? '⚠️'
        : '❌';

    const lessonDir = getLessonDir(result.lesson);
    console.log(`${status} Lesson ${result.lesson.toString().padStart(2, '0')}: ${lessonDir}`);

    if (result.exerciseExists) {
      totalExercises++;
      if (result.testsPass) totalPassing++;
    } else {
      totalMissing++;
    }

    if (result.errors.length > 0) {
      for (const error of result.errors) {
        console.log(`   └─ ${error}`);
      }
    }
  }

  console.log('═'.repeat(70));
  console.log(`\n📊 Summary:`);
  console.log(`   Lessons with exercises: ${totalExercises}/${LESSONS.length}`);
  console.log(`   Passing tests: ${totalPassing}/${totalExercises}`);
  console.log(`   Missing exercises: ${totalMissing}`);

  if (totalMissing > 0) {
    console.log(`\n⚠️  Some lessons are missing exercises.`);
  }

  if (totalPassing === totalExercises && totalExercises > 0) {
    console.log(`\n✅ All exercise tests pass!`);
  }
}

// Main execution
console.log('🔍 Verifying exercises...\n');

const results = LESSONS.map(verifyLesson);
printResults(results);

// Exit with error code if any issues found
const hasErrors = results.some(r => r.errors.length > 0 && r.exerciseExists);
process.exit(hasErrors ? 1 : 0);
