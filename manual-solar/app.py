from flask import Flask, render_template, url_for, request, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc
from sqlalchemy.dialects.sqlite import DATE, DECIMAL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert
from datetime import datetime, timezone

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data/data.db'
db = SQLAlchemy(app)

class Record(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(DATE, nullable=False, unique=True)
    value = db.Column(DECIMAL(5, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=True, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Record id={self.id}, date={self.date}, value={self.value}, created_at={self.created_at}, updated_at={self.updated_at}>"

@app.route("/", defaults={"page": 1})
@app.route('/page/<int:page>', methods=['POST', 'GET'])
def index(page):
    PER_PAGE = 20
    if request.method == 'POST':
        date = datetime.strptime(request.form['date'], "%Y-%m-%d").date()
        new_record = Record(date=date, value=request.form['kwh'])
        try:
            db.session.add(new_record)
            db.session.commit()
            return redirect('/')
        except Exception as e:
            app.logger.error(e)
            return render_template('error.html')
        
    pagination = Record.query.order_by(desc(Record.date)).paginate(page=page, per_page=PER_PAGE, error_out=False)
    app.logger.info({
        "page": pagination.page,
        "per_page": pagination.per_page,
        "total_items": pagination.total,
        "first": pagination.first,
        "last": pagination.last,
        "total_pages": pagination.pages,
        "has_prev": pagination.has_prev,
        "prev_num": pagination.prev_num,
        "has_next": pagination.has_next,
        "next_num": pagination.next_num,
    })
    pagination_widget = pagination.iter_pages(left_edge=0, right_edge=0, left_current=2, right_current=2)
    return render_template('index.html', records=pagination.items, pagination=pagination, pagination_widget=pagination_widget)

@app.route('/delete/<int:id>')
def delete(id):
    record = Record.query.get_or_404(id)
    try:
        db.session.delete(record)
        db.session.commit()
    except Exception as e:
        app.logger.error(e)
        return render_template('error.html')
    
    return redirect('/')

@app.route('/bulk', methods=['POST', 'GET'])
def bulk():
    # Constants
    MAX_ROWS = 500
    errors = []
    total_rows = 0    
    successful_rows = 0

    # Get the input data
    data = request.form.get('data')
    if not data:
        return render_template('bulk.html', result={
            "total_rows": 0,
            "successful_rows": 0,
            "error_rows": 0,
            "errors": [],
        }, max_rows=MAX_ROWS)

    # Split rows and enforce row limit
    rows = [row for row in data.strip().splitlines() if row.strip()]
    total_rows = len(rows)
    if total_rows > MAX_ROWS:
        return render_template('bulk.html', result={
            "total_rows": total_rows,
            "successful_rows": 0,
            "error_rows": total_rows,
            "errors": ["Exceeded maximum allowed rows."]
        }, max_rows=MAX_ROWS)

    # Prepare batch insert data
    records_to_upsert  = []
    for idx, row in enumerate(rows, start=1):
        try:
            columns = row.split(',')
            if len(columns) != 2:
                raise ValueError(f"Row {idx}: Incorrect number of columns.")
            
            date_str, kwh_str = columns[0].strip(), columns[1].strip()

            # Validate date
            date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Validate kWh
            kwh = float(kwh_str)
            if kwh < 0:
                raise ValueError(f"Row {idx}: kWh value must be non-negative.")

            # Add to insert list
            records_to_upsert.append(Record(date=date, value=kwh))
        
        except ValueError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    if not records_to_upsert:
        return render_template('bulk.html', result={
            "total_rows": total_rows,
            "successful_rows": 0,
            "error_rows": total_rows,
            "errors": ["Nothing to upload."]
        }, max_rows=MAX_ROWS)

    records_to_upsert = [
        {
            "date": record.date, 
            "value": record.value, 
            "created_at": datetime.now(timezone.utc), 
            "updated_at": datetime.now(timezone.utc)
        }
        for record in records_to_upsert
    ]

    try:
        stmt = insert(Record).values(records_to_upsert).on_conflict_do_update(
            index_elements=["date"],  # Ensure uniqueness constraint on 'date'
            set_={
                "value": insert(Record).excluded.value,  # Use the incoming value for update
                "updated_at": datetime.now(timezone.utc),
            },
        )
        result = db.session.execute(stmt)
        successful_rows += result.rowcount

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        errors.append(f"Unexpected error: {str(e)}")

    # Render response
    result = {
        "total_rows": total_rows,
        "successful_rows": successful_rows,
        "error_rows": len(errors),
        "errors": errors
    }
    return render_template('bulk.html', result=result, max_rows=MAX_ROWS)


if __name__ == "__main__":
    app.run(debug=True)