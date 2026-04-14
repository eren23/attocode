// Style issues — true positives

public class NullReturns {
    public Object badReturnNull() {
        return null;  // expect: java/java-null-return
    }

    public String badConditionalNull(boolean condition) {
        if (condition) {
            return "ok";
        }
        return null;  // expect: java/java-null-return
    }
}
