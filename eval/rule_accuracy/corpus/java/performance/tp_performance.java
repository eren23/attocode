// Performance issues — true positives

public class Performance {
    public String badStringConcat(String[] items) {
        String result = "";
        for (String item : items) {
            result += "item: ";  // expect: java/java-string-concat-loop
            result += item;
        }
        return result;
    }
}
