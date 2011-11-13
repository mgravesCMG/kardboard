import csv
import cStringIO
import datetime
import importlib

from dateutil import relativedelta
from flask import (
    render_template,
    make_response,
    request,
    redirect,
    session,
    url_for,
    flash,
    abort,
)

import kardboard.auth
from kardboard.version import VERSION
from kardboard.app import app
from kardboard.models import Kard, DailyRecord, Q, Person, BlockerRecord
from kardboard.forms import get_card_form, _make_choice_field_ready, LoginForm, CardBlockForm, CardUnblockForm
import kardboard.util
from kardboard.util import (
    month_range,
    slugify,
    make_start_date,
    make_end_date,
    month_ranges,
    log_exception,
)
from kardboard.charts import (
    ThroughputChart,
    MovingCycleTimeChart,
    CumulativeFlowChart,
    CycleDistributionChart
)


def dashboard(year=None, month=None, day=None):
    date = kardboard.util.now()
    now = kardboard.util.now()
    scope = 'current'

    if year:
        date = date.replace(year=year)
        scope = 'year'
    if month:
        date = date.replace(month=month)
        scope = 'month'
        start, end = month_range(date)
        date = end
    if day:
        date = date.replace(day=day)
        scope = 'day'

    date = make_end_date(date=date)

    wip_cards = list(Kard.in_progress(date))
    wip_cards = sorted(wip_cards, key=lambda c: c.current_cycle_time(date))
    wip_cards.reverse()

    backlog_cards = Kard.backlogged(date).order_by('key')

    metrics = [
        {'Ave. Cycle Time': Kard.objects.moving_cycle_time(
            year=date.year, month=date.month, day=date.day)},
        {'Done this week': Kard.objects.done_in_week(
            year=date.year, month=date.month, day=date.day).count()},
        {'Done this month':
            Kard.objects.done_in_month(
                year=date.year, month=date.month, day=date.day).count()},
        {'On the board': len(wip_cards) + backlog_cards.count()},
    ]

    title = "Dashboard"
    if scope == 'year':
        title += " for %s"
    if scope == 'month':
        title += " for %s/%s" % (date.month, date.year)
    if scope == 'day' or scope == 'current':
        title += " for %s/%s/%s" % (date.month, date.day, date.year)

    forward_date = date + relativedelta.relativedelta(days=1)
    back_date = date - relativedelta.relativedelta(days=1)

    if forward_date > now:
        forward_date = None

    context = {
        'forward_date': forward_date,
        'back_date': back_date,
        'scope': scope,
        'date': date,
        'title': title,
        'metrics': metrics,
        'wip_cards': wip_cards,
        'backlog_cards': backlog_cards,
        'updated_at': now,
        'version': VERSION,
    }

    return render_template('dashboard.html', **context)


def team(team_slug=None):
    date = datetime.datetime.now()
    date = make_end_date(date=date)
    teams = app.config.get('CARD_TEAMS', [])

    team_mapping = {}
    for team in teams:
        team_mapping[slugify(team)] = team

    target_team = None
    if team_slug:
        target_team = team_mapping.get(team_slug, None)
        if not team:
            abort(404)

    metrics = [
        {'Ave. Cycle Time': Kard.objects.filter(team=target_team).moving_cycle_time(
            year=date.year, month=date.month, day=date.day)},
        {'Done this week': Kard.objects.filter(team=target_team).done_in_week(
            year=date.year, month=date.month, day=date.day).count()},
        {'Done this month':
            Kard.objects.filter(team=target_team).done_in_month(
                year=date.year, month=date.month, day=date.day).count()},
        {'On the board': Kard.objects.filter(team=target_team).count()},
    ]

    states = app.config.get('CARD_STATES', [])
    states_data = []
    for state in states:
        state_data = {}
        wip_cards = Kard.in_progress().filter(state=state, team=target_team)
        wip_cards = sorted(wip_cards, key=lambda c: c.current_cycle_time())
        wip_cards.reverse()
        state_data['wip_cards'] = wip_cards
        state_data['backlog_cards'] = Kard.backlogged().filter(state=state, team=target_team)
        state_data['done_cards'] = Kard.objects.done().filter(state=state, team=target_team).order_by('-done_date')
        state_data['title'] = state
        if len(state_data['wip_cards']) > 0 or \
            state_data['backlog_cards'].count() > 0 or\
            state_data['done_cards'].count() > 0:
            states_data.append(state_data)

    title = "%s cards" % target_team

    context = {
        'title': title,
        'states_data': states_data,
        'states_count': len(states_data),
        'metrics': metrics,
        'date': date,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    return render_template('state.html', **context)


def state():
    date = datetime.datetime.now()
    date = make_end_date(date=date)
    states = app.config.get('CARD_STATES', [])

    states_data = []
    for state in states:
        state_data = {}
        wip_cards = Kard.in_progress().filter(state=state)
        wip_cards = sorted(wip_cards, key=lambda c: c.current_cycle_time())
        wip_cards.reverse()
        state_data['wip_cards'] = wip_cards
        state_data['backlog_cards'] = Kard.backlogged().filter(state=state)
        state_data['title'] = state
        if len(state_data['wip_cards']) > 0 or \
            state_data['backlog_cards'].count() > 0:
            states_data.append(state_data)

    title = "Cards in progress"

    wip_cards = Kard.in_progress(date)
    backlog_cards = Kard.backlogged(date)
    metrics = [
        {'Ave. Cycle Time': Kard.objects.moving_cycle_time(
            year=date.year, month=date.month, day=date.day)},
        {'Done this week': Kard.objects.done_in_week(
            year=date.year, month=date.month, day=date.day).count()},
        {'Done this month':
            Kard.objects.done_in_month(
                year=date.year, month=date.month, day=date.day).count()},
        {'On the board': wip_cards.count() + backlog_cards.count()},
    ]

    context = {
        'title': title,
        'states_data': states_data,
        'states_count': len(states_data),
        'metrics': metrics,
        'date': date,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    return render_template('state.html', **context)


def done():
    cards = Kard.objects.done()
    cards = sorted(cards, key=lambda c: c.done_date)
    cards.reverse()

    context = {
        'title': "Completed Cards",
        'cards': cards,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    return render_template('done.html', **context)


def done_report(year_number, month_number):
    cards = Kard.objects.done_in_month(year_number, month_number)
    cards = sorted(cards, key=lambda c: c.done_date)
    cards.reverse()

    context = {
        'title': "Completed Cards: %s/%s: %s Done" % (month_number,
            year_number, len(cards)),
        'cards': cards,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    response = make_response(render_template('done-report.txt', **context))
    response.headers['Content-Type'] = "text/plain"
    return response


def _init_new_card_form(*args, **kwargs):
    return _init_card_form(*args, new=True, **kwargs)


def _init_card_form(*args, **kwargs):
    new = kwargs.get('new', False)
    if new:
        del kwargs['new']
    klass = get_card_form(new=new)
    f = klass(*args, **kwargs)
    choices = app.config.get('CARD_CATEGORIES')
    if choices:
        f.category.choices = _make_choice_field_ready(choices)

    states = app.config.get('CARD_STATES')
    if states:
        f.state.choices = _make_choice_field_ready(states)

    teams = app.config.get('CARD_TEAMS')
    if teams:
        f.team.choices = _make_choice_field_ready(teams)

    return f


@kardboard.auth.login_required
def card_add():
    f = _init_new_card_form(request.values)
    card = Kard()
    f.populate_obj(card)

    if request.method == "POST":
        if f.key.data and not f.title.data:
            try:
                f.title.data = card.ticket_system.get_title(key=f.key.data)
            except Exception, e:
                log_exception(e, "Error getting card title via helper")
                pass

        if f.validate():
            # Repopulate now that some data may have come from the ticket
            # helper above
            f.populate_obj(card)
            card.save()
            flash("Card %s successfully added" % card.key)
            return redirect(url_for("card_edit", key=card.key))

    context = {
        'title': "Add a card",
        'form': f,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }
    return render_template('card-add.html', **context)


@kardboard.auth.login_required
def card_edit(key):
    try:
        card = Kard.objects.get(key=key)
    except Kard.DoesNotExist:
        abort(404)

    f = _init_card_form(request.form, card)

    if request.method == "POST" and f.validate():
        f.populate_obj(card)
        card.save()
        flash("Card %s successfully edited" % card.key)
        return redirect(url_for("card_edit", key=card.key))

    context = {
        'title': "Edit a card",
        'form': f,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    return render_template('card-add.html', **context)


@kardboard.auth.login_required
def card(key):
    try:
        card = Kard.objects.get(key=key)
    except Kard.DoesNotExist:
        abort(404)

    context = {
        'title': "%s -- %s" % (card.key, card.title),
        'card': card,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }
    return render_template('card.html', **context)


@kardboard.auth.login_required
def card_delete(key):
    try:
        card = Kard.objects.get(key=key)
    except Kard.DoesNotExist:
        abort(404)

    if request.method == "POST" and request.form.get('delete'):
        card.delete()
        return redirect(url_for("dashboard"))
    elif request.method == "POST" and request.form.get('cancel'):
        return redirect(url_for("card", key=card.key))

    context = {
        'title': "%s -- %s" % (card.key, card.title),
        'card': card,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }
    return render_template('card-delete.html', **context)


@kardboard.auth.login_required
def card_block(key):
    try:
        card = Kard.objects.get(key=key)
        action = 'block'
        if card.blocked:
            action = 'unblock'
    except Kard.DoesNotExist:
        abort(404)

    if not session.get('next_url'):
        next_url = request.args.get('next', '/')
        session['next_url'] = next_url

    now = datetime.datetime.now()
    if action == 'block':
        f = CardBlockForm(request.form, blocked_at=now)
    if action == 'unblock':
        f = CardUnblockForm(request.form, unblocked_at=now)

    should_redir = False

    if 'cancel' in request.form.keys():
        should_redir = True
    elif request.method == "POST" and f.validate():
        should_redir = True
        if action == 'block':
            blocked_at = datetime.datetime.combine(
                f.blocked_at.data, datetime.time())
            blocked_at = make_start_date(date=blocked_at)
            result = card.block(f.reason.data, blocked_at)
            if result:
                card.save()
                flash("%s blocked" % card.key)
        if action == 'unblock':
            unblocked_at = datetime.datetime.combine(
                f.unblocked_at.data, datetime.time())
            unblocked_at = make_end_date(date=unblocked_at)
            result = card.unblock(unblocked_at)
            if result:
                card.save()
                flash("%s unblocked" % card.key)

    if should_redir:
        next_url = session.get('next_url', '/')
        if 'next_url' in session:
            del session['next_url']
        return redirect(next_url)

    context = {
        'title': "%s a card" % (action.capitalize(), ),
        'action': action,
        'card': card,
        'form': f,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    return render_template('card-block.html', **context)


def quick():
    key = request.args.get('key', None)
    if not key:
        url = url_for('dashboard')
        return redirect(url)

    try:
        card = Kard.objects.get(key=key)
    except Kard.DoesNotExist:
        card = None

    if not card:
        try:
            card = Kard.objects.get(key=key.upper())
        except Kard.DoesNotExist:
            pass

    if card:
        url = url_for('card_edit', key=card.key)
    else:
        url = url_for('card_add', key=key)

    return redirect(url)

@kardboard.auth.login_required
def card_export():
    output = cStringIO.StringIO()
    export = csv.DictWriter(output, Kard.EXPORT_FIELDNAMES)
    header_row = [(v, v) for v in Kard.EXPORT_FIELDNAMES]
    export.writerow(dict(header_row))
    for c in Kard.objects.all():
        row = {}
        card = c.to_mongo()
        for name in Kard.EXPORT_FIELDNAMES:
            try:
                value = card[name]
                if hasattr(value, 'second'):
                    value = value.strftime("%m/%d/%Y")
                if hasattr(value, 'strip'):
                    value = value.strip()
                row[name] = value
            except KeyError:
                row[name] = ''
        export.writerow(row)

    response = make_response(output.getvalue())
    content_type = response.headers['Content-Type']
    response.headers['Content-Type'] = \
        content_type.replace('text/html', 'text/plain')
    return response


def chart_index():
    context = {
        'title': "Charts",
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }
    return render_template('charts.html', **context)


def chart_throughput(months=6, start=None):
    start = start or datetime.datetime.today()

    months_ranges = month_ranges(start, months)

    month_counts = []
    for arange in months_ranges:
        start, end = arange
        num = Kard.objects.filter(done_date__gte=start,
            done_date__lte=end).count()
        month_counts.append((start.strftime("%B"), num))

    chart = ThroughputChart(900, 300)
    chart.add_bars(month_counts)

    context = {
        'title': "How much have we done?",
        'updated_at': datetime.datetime.now(),
        'chart': chart,
        'month_counts': month_counts,
        'version': VERSION,
    }

    return render_template('chart-throughput.html', **context)


def chart_cycle(months=6, year=None, month=None, day=None):
    today = datetime.datetime.today()
    if day:
        end_day = datetime.datetime(year=year, month=month, day=day)
        if end_day > today:
            end_day = today
    else:
        end_day = today

    start_day = end_day - relativedelta.relativedelta(months=months)
    start_day = make_start_date(date=start_day)
    end_day = make_end_date(date=end_day)

    records = DailyRecord.objects.filter(
        date__gte=start_day,
        date__lte=end_day)

    daily_moving_averages = [(r.date, r.moving_cycle_time) for r in records]
    daily_moving_lead = [(r.date, r.moving_lead_time) for r in records]

    chart = MovingCycleTimeChart(900, 300)
    chart.add_first_line(daily_moving_lead)
    chart.add_line(daily_moving_averages)
    chart.set_legend(('Lead time', 'Cycle time'))

    daily_moving_averages.reverse()  # reverse order for display
    context = {
        'title': "How quick can we do it?",
        'updated_at': datetime.datetime.now(),
        'chart': chart,
        'daily_averages': daily_moving_averages,
        'daily_lead': daily_moving_lead,
        'version': VERSION,
    }

    return render_template('chart-cycle.html', **context)


def chart_cycle_distribution(months=3):
    ranges = (
        (0, 4, "< 5 days"),
        (5, 10, "5-10 days"),
        (11, 15, "11-15 days"),
        (16, 20, "16-20 days"),
        (21, 25, "21-25 days"),
        (26, 30, "26-30 days",),
        (31, 9999, "> 30 days"),
    )
    today = datetime.datetime.today()
    start_day = today - relativedelta.relativedelta(months=months)
    start_day = make_start_date(date=start_day)
    end_day = make_end_date(date=today)

    context = {
        'title': "How quick can we do it?",
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }

    query = Q(done_date__gte=start_day) & Q(done_date__lte=end_day)
    total = Kard.objects.filter(query).count()
    if total == 0:
        context = {
            'error': "Zero cards were completed in the past %s months" % months
        }
        return render_template('chart-cycle-distro.html', **context)

    distro = []
    for row in ranges:
        lower, upper, label = row
        query = Q(done_date__gte=start_day) & Q(done_date__lte=end_day) & \
            Q(_cycle_time__gte=lower) & Q(_cycle_time__lte=upper)
        pct = Kard.objects.filter(query).count() / float(total)
        distro.append((label, pct))

    chart = CycleDistributionChart(700, 400)
    chart.add_data([r[1] for r in distro])
    chart.set_pie_labels([r[0] for r in distro])
    context = {
        'data': distro,
        'chart': chart,
        'title': "How quick can we do it?",
        'updated_at': datetime.datetime.now(),
        'distro': distro,
        'version': VERSION,
    }
    return render_template('chart-cycle-distro.html', **context)


def robots():
    response = make_response(render_template('robots.txt'))
    content_type = response.headers['Content-type']
    content_type.replace('text/html', 'text/plain')
    return response


def chart_flow(months=3):
    end = kardboard.util.now()
    months_ranges = month_ranges(end, months)

    start_day = make_start_date(date=months_ranges[0][0])
    end_day = make_end_date(date=end)

    records = DailyRecord.objects.filter(
        date__gte=start_day,
        date__lte=end_day)

    chart = CumulativeFlowChart(900, 300)
    chart.add_data([r.backlog_cum for r in records])
    chart.add_data([r.in_progress_cum for r in records])
    chart.add_data([r.done for r in records])
    chart.setup_grid(records)

    records.order_by('-date')
    context = {
        'title': "Cumulative Flow",
        'updated_at': datetime.datetime.now(),
        'chart': chart,
        'flowdata': records,
        'version': VERSION,
    }

    return render_template('chart-flow.html', **context)


def login():
    f = LoginForm(request.form)

    if not session.get('next_url'):
        next_url = request.args.get('next', '/')
        session['next_url'] = next_url

    if request.method == "POST" and f.validate():
        helper_setting = app.config['TICKET_HELPER']
        modname = '.'.join(helper_setting.split('.')[:-1])
        klassnam = helper_setting.split('.')[-1]
        mod = importlib.import_module(modname)
        klass = getattr(mod, klassnam)

        helper = klass(app.config, None)
        result = helper.login(f.username.data, f.password.data)
        if result:
            session['username'] = f.username.data
            next_url = session.get('next_url', '/')
            if 'next_url' in session:
                del session['next_url']
            return redirect(next_url)

    context = {
        'title': "Login",
        'form': f,
        'updated_at': datetime.datetime.now(),
        'version': VERSION,
    }
    return render_template('login.html', **context)


def logout():
    if 'username' in session:
        del session['username']
    next_url = request.args.get('next') or '/'
    return redirect(next_url)

def person(name):
    try:
        person = Person.objects.get(name=name)
    except Person.DoesNotExist:
        abort(404)

    in_progress_reported = [k for k in person.reported if not k.done_date]
    in_progress_reported.sort(key=lambda r: r.current_cycle_time())
    in_progress_reported.reverse()

    in_progress_developed = [k for k in person.developed if not k.done_date]
    in_progress_developed.sort(key=lambda r: r.current_cycle_time())
    in_progress_developed.reverse()

    in_progress_tested = [k for k in person.tested if not k.done_date]
    in_progress_tested.sort(key=lambda r: r.current_cycle_time())
    in_progress_tested.reverse()

    reported = [k for k in person.reported if k.done_date]
    reported.sort(key=lambda r: r.done_date)
    reported.reverse()

    developed = [k for k in person.developed if k.done_date]
    developed.sort(key=lambda r: r.done_date)
    developed.reverse()

    tested = [k for k in person.tested if k.done_date]
    tested.sort(key=lambda r: r.done_date)
    tested.reverse()

    context = {
        'title': "%s's information" % person.name,
        'person': person,
        'in_progress_reported': in_progress_reported,
        'in_progress_developed': in_progress_developed,
        'in_progres_tested': in_progress_tested,
        'reported': reported,
        'developed': developed,
        'tested': tested,
        'updated_at': person.updated_at,
        'version': VERSION,
    }
    return render_template('person.html', **context)
