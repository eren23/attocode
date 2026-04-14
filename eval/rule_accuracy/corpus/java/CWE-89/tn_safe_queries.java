// SQL — true negatives (safe patterns)
// no-expect: These should NOT trigger SQL injection rules

public class SafeQueries {
    public void safeParameterized(String userInput) throws Exception {
        PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
        ps.setString(1, userInput);
        ps.executeQuery();
    }

    public void safeConstant() throws Exception {
        conn.createStatement().executeQuery("SELECT count(*) FROM users");
    }
}
