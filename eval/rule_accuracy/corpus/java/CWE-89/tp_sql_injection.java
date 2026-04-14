// SQL injection — true positives for rule accuracy testing
// INTENTIONALLY insecure — nosec

public class SqlInjection {
    public void badCreateQuery(String userInput) {
        em.createQuery("SELECT u FROM User u WHERE u.name = '" + userInput + "'");  // expect: java/java-sql-concat
    }

    public void badStatement(String id) throws Exception {
        Statement stmt = conn.createStatement();
        stmt.executeQuery("SELECT * FROM users WHERE id = " + id);  // expect: security/java_sql_concat
    }
}
