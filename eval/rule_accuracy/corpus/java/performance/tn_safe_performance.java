// Performance — true negatives (safe patterns)
// no-expect: These should NOT trigger performance rules

public class SafePerformance {
    public String safeStringBuilder(String[] items) {
        StringBuilder sb = new StringBuilder();
        for (String item : items) {
            sb.append("item: ").append(item);
        }
        return sb.toString();
    }
}
