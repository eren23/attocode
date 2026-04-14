// Correctness issues — true positives

public class Correctness {
    public Object badCatchAll() {
        try {
            return riskyOperation();
        } catch (Exception e) {  // expect: java/java-catch-exception
            return null;  // expect: java/java-null-return
        }
    }
}
